"""
语义分块器模块

该模块提供基于文档结构的智能文本分块功能，主要特点：
1. 根据文件名自动选择适合的分块策略
2. 支持 Parent-Child 分块模式（父子文档关联）
3. 保留文档的层次结构和语义完整性
4. 为不同业务场景定制专门的分块逻辑

分块策略：
- 洗涤养护文档：按季节和材质分层，进一步拆分为洗涤和养护子块
- 颜色选择文档：按章节分层，拆分为独立的建议项
- 其他文档：简单整体分块

Parent-Child 模式优势：
- Child 块用于精确检索（更小的粒度）
- Parent 块用于生成回答（完整的上下文）
- 通过 metadata 建立父子关联关系
"""

import re
from typing import List, Tuple


def split_by_structure(text: str, filename: str) -> List[dict]:
    """
    根据文档结构选择合适的分块策略
    
    通过分析文件名判断文档类型，自动应用对应的分块算法。
    
    Args:
        text: 待分块的原始文本内容
        filename: 文件名，用于判断文档类型
        
    Returns:
        List[dict]: 分块结果列表，每个元素包含：
            - content (str): 分块的文本内容
            - metadata (dict): 元数据，包括来源、类型、标题等信息
            
    Example:
        >>> chunks = split_by_structure("文本内容", "洗涤养护.txt")
        >>> # 返回按季节和材质分层的多个语义块
    """
    # 根据文件名关键词选择对应的分块策略
    if "洗涤养护" in filename:
        return _split_washing_care(text, filename)
    elif "颜色选择" in filename:
        return _split_color_guide(text, filename)
    else:
        return _split_simple(text, filename)


def _split_washing_care(text: str, filename: str) -> List[dict]:
    """
    洗涤养护文档专用分块策略
    
    采用两层嵌套结构：
    第一层：按季节划分（一、二、三...）
    第二层：按材质划分（1. xxx材质、2. xxx材质...）
    第三层：按洗涤/养护拆分（如果同时存在两者）
    
    这种细粒度分块有利于用户针对特定季节和材质的精准查询。
    
    Args:
        text: 洗涤养护文档的完整文本
        filename: 文件名
        
    Returns:
        List[dict]: 分块结果，通常是 child 类型的细粒度块
        
    Note:
        - 使用正则表达式匹配中文序号（一、二、三...）和阿拉伯数字序号（1. 2. 3...）
        - 如果同时包含洗涤和养护信息，会拆分为两个独立的 child 块
        - 每个 child 块都通过 parent_content 关联到完整的父文档
    """
    chunks = []
    
    # 匹配季节标题：一、春季衣物清洗 二、夏季衣物护理...
    season_pattern = re.compile(r'(?:^|\n)([一二三四五六七八九十]、[^\n]+)')
    
    # 匹配材质标题：1. 棉质材质 2. 羊毛材质...
    material_pattern = re.compile(r'(?:^|\n)(\d+\.\s*[^\n]+材质[^\n]*)')

    # 遍历所有季节段落
    for season_match in season_pattern.finditer(text):
        # 提取季节标题和位置信息
        season_title = season_match.group(1).strip()
        season_start = season_match.start()
        
        # 查找下一个季节的起始位置，确定当前季节的范围
        next_season_start = text.find(season_match.group(0), season_start + 1)
        if next_season_start == -1:
            # 最后一个季节，取到文本末尾
            season_text = text[season_start:]
        else:
            # 截取当前季节的完整文本
            season_text = text[season_start:next_season_start]

        # 在当前季节内遍历所有材质段落
        for mat_match in material_pattern.finditer(season_text):
            # 提取材质标题和位置信息
            mat_title = mat_match.group(1).strip()
            mat_start_in_season = mat_match.start()
            mat_start = season_start + mat_start_in_season

            # 查找下一个材质的起始位置，确定当前材质的范围
            next_mat = material_pattern.search(season_text, mat_start_in_season + 1)
            if next_mat:
                mat_end = season_start + next_mat.start()
            else:
                # 最后一个材质，取到季节文本末尾
                mat_end = season_start + len(season_text)

            # 提取完整的父文档内容（某个季节下某种材质的全部信息）
            parent_content = text[mat_start:mat_end].strip()
            
            # 构建层级标题：季节 > 材质
            parent_title = f"{season_title} > {mat_title}"

            # 在父内容中查找洗涤和养护的具体说明
            wash_match = re.search(r'洗涤[：:][^\n]*', parent_content)
            care_match = re.search(r'养护[：:][^\n]*', parent_content)

            # 如果同时包含洗涤和养护信息，拆分为两个 child 块
            if wash_match and care_match:
                # 创建洗涤子块
                child_wash = f"{parent_title}\n{wash_match.group(0)}"
                # 创建养护子块
                child_care = f"{parent_title}\n{care_match.group(0)}"

                # 添加洗涤子块到结果列表
                chunks.append({
                    "content": child_wash,
                    "metadata": {
                        "source": filename,              # 来源文件
                        "chunk_type": "child",           # 子块类型
                        "section_title": parent_title,   # 章节标题
                        "parent_content": parent_content, # 关联的父文档完整内容
                    }
                })
                
                # 添加养护子块到结果列表
                chunks.append({
                    "content": child_care,
                    "metadata": {
                        "source": filename,
                        "chunk_type": "child",
                        "section_title": parent_title,
                        "parent_content": parent_content,
                    }
                })
            else:
                # 只有单一信息或格式不标准，保持为 parent 块
                chunks.append({
                    "content": parent_content,
                    "metadata": {
                        "source": filename,
                        "chunk_type": "parent",          # 父块类型
                        "section_title": parent_title,
                        "parent_content": parent_content,
                    }
                })

    # 如果没有成功解析出任何块，降级为简单分块策略
    return chunks if chunks else _split_simple(text, filename)


def _split_color_guide(text: str, filename: str) -> List[dict]:
    """
    颜色选择指南专用分块策略
    
    按章节（1. xxx、2. xxx...）划分，然后将每个章节内的具体建议项
    拆分为独立的 child 块，便于针对具体场景的精准检索。
    
    Args:
        text: 颜色选择指南的完整文本
        filename: 文件名
        
    Returns:
        List[dict]: 分块结果，通常是 child 类型的建议项块
        
    Note:
        - 每个章节可能包含多个建议项（如不同体型、场合的推荐）
        - 只保留长度超过 20 字符的行作为有效建议
        - 每个 child 块都关联到完整的父章节内容
    """
    chunks = []
    
    # 匹配章节标题：1. 根据肤色选择 2. 根据场合选择...
    section_pattern = re.compile(r'(?:^|\n)(\d+\.\s+[^\n]+)')

    # 查找所有章节标题及其位置
    matches = list(section_pattern.finditer(text))
    
    # 遍历所有章节
    for i, match in enumerate(matches):
        # 提取章节标题
        section_title = match.group(1).strip()
        
        # 确定章节范围：从当前标题到下一个标题之间
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        
        # 提取完整的父章节内容
        parent_content = text[start:end].strip()

        # 将章节内容按行拆分，过滤掉空行和章节标题行
        child_lines = [line.strip() for line in parent_content.split("\n") 
                      if line.strip() and not re.match(r'^\d+\.', line.strip())]

        # 为每个有效的建议行创建 child 块
        for child_line in child_lines:
            # 只处理长度足够的有效建议（避免过短的无意义行）
            if len(child_line) > 20:
                # 组合章节标题和具体建议作为子块内容
                child_content = f"{section_title}\n{child_line}"
                
                chunks.append({
                    "content": child_content,
                    "metadata": {
                        "source": filename,              # 来源文件
                        "chunk_type": "child",           # 子块类型
                        "section_title": section_title,  # 章节标题
                        "parent_content": parent_content, # 关联的父章节完整内容
                    }
                })

    # 如果没有成功解析出任何块，降级为简单分块策略
    return chunks if chunks else _split_simple(text, filename)


def _split_simple(text: str, filename: str) -> List[dict]:
    """
    简单分块策略（兜底方案）
    
    当文档不符合特定格式或解析失败时，将整个文本作为一个单独的块。
    确保任何文档都能被处理，不会因格式问题导致上传失败。
    
    Args:
        text: 待分块的文本内容
        filename: 文件名
        
    Returns:
        List[dict]: 单个块的列表，类型为 parent
        
    Note:
        - 适用于短文档或格式不规范的文档
        - 作为其他分块策略失败时的降级方案
    """
    return [{
        "content": text,
        "metadata": {
            "source": filename,              # 来源文件
            "chunk_type": "parent",          # 父块类型（整个文档）
            "section_title": "",             # 无章节标题
            "parent_content": text,          # 完整文档内容
        }
    }]


if __name__ == "__main__":
    """
    主程序入口，用于测试各种文档的分块效果
    """
    import os
    
    # 指定测试数据目录
    data_dir = r"D:\AI coding\RAG\data"
    
    # 遍历数据目录中的所有文件
    for fname in os.listdir(data_dir):
        fpath = os.path.join(data_dir, fname)
        
        # 读取文件内容
        with open(fpath, "r", encoding="utf-8") as f:
            text = f.read()
        
        # 执行分块处理
        chunks = split_by_structure(text, fname)
        
        # 打印分块统计信息
        print(f"\n=== {fname}: {len(chunks)} chunks ===")
        
        # 打印前 3 个块的详细信息（避免输出过多）
        for i, ch in enumerate(chunks[:3]):
            print(f"  [{i}] type={ch['metadata']['chunk_type']} | title={ch['metadata']['section_title'][:40]}")
            print(f"       content: {ch['content'][:80]}...")

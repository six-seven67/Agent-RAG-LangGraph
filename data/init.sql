-- ============================================================================
-- RAG 智能客服系统 — MySQL 数据库初始化脚本
-- ============================================================================
-- 使用方法：
--   1. 先创建数据库：
--      CREATE DATABASE rag_system CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
--
--   2. 导入本文件：
--      mysql -u root -p rag_system < init.sql
--
--   3. 或者在 MySQL 客户端中：
--      source /path/to/init.sql;
-- ============================================================================

-- 创建数据库（如尚不存在）
CREATE DATABASE IF NOT EXISTS `rag_system`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `rag_system`;

-- ============================================================================
-- 1. 用户表 (users)
-- ============================================================================
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users` (
    `id`            INT             NOT NULL AUTO_INCREMENT  COMMENT '用户唯一ID',
    `username`      VARCHAR(50)     NOT NULL                 COMMENT '登录用户名',
    `password_hash` VARCHAR(255)    NOT NULL                 COMMENT 'bcrypt 密码哈希值',
    `email`         VARCHAR(100)    DEFAULT NULL             COMMENT '邮箱地址',
    `is_active`     TINYINT(1)      NOT NULL DEFAULT 1      COMMENT '账号启用状态：1=启用, 0=禁用',
    `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    `updated_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_username` (`username`),
    KEY `idx_is_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户账号表';


-- ============================================================================
-- 2. 对话历史表 (chat_history)  —— 用户隔离核心
-- ============================================================================
DROP TABLE IF EXISTS `chat_history`;
CREATE TABLE `chat_history` (
    `id`            INT             NOT NULL AUTO_INCREMENT  COMMENT '消息唯一ID',
    `user_id`       INT             NOT NULL                 COMMENT '所属用户ID（用户隔离）',
    `session_id`    VARCHAR(36)     NOT NULL                 COMMENT '会话UUID',
    `role`          ENUM('user','assistant') NOT NULL        COMMENT '消息角色：user=用户提问, assistant=AI回答',
    `content`       TEXT            NOT NULL                 COMMENT '消息文本内容',
    `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '消息时间',
    PRIMARY KEY (`id`),
    KEY `idx_user_session` (`user_id`, `session_id`),
    KEY `idx_session_time` (`session_id`, `created_at`),
    CONSTRAINT `fk_chat_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='对话历史表（用户隔离）';


-- ============================================================================
-- 3. 知识库文档元数据表 (knowledge_docs)  —— 用户隔离核心
-- ============================================================================
DROP TABLE IF EXISTS `knowledge_docs`;
CREATE TABLE `knowledge_docs` (
    `id`            INT             NOT NULL AUTO_INCREMENT  COMMENT '文档唯一ID',
    `user_id`       INT             NOT NULL                 COMMENT '所属用户ID（用户隔离）',
    `filename`      VARCHAR(255)    NOT NULL                 COMMENT '上传的原始文件名',
    `md5_hash`      VARCHAR(32)     NOT NULL                 COMMENT '文件内容MD5（用户级去重）',
    `chunk_count`   INT             NOT NULL DEFAULT 0       COMMENT '语义分块数量',
    `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
    PRIMARY KEY (`id`),
    KEY `idx_user_md5` (`user_id`, `md5_hash`),
    KEY `idx_user_time` (`user_id`, `created_at`),
    CONSTRAINT `fk_knowledge_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库文档元数据表（用户隔离）';


-- ============================================================================
-- 4. 可选：插入一个测试用户（密码为 "admin123"）
--    bcrypt hash of "admin123" 使用 12 rounds
--    生产环境请删除此段或修改密码！
-- ============================================================================
-- INSERT INTO `users` (`username`, `password_hash`, `email`, `is_active`)
-- VALUES ('admin', '$2b$12$LJ3m4ys3YOlDkOmMrPJ7OOCCpNn1XGM8FG.3daSFrL5Xf6v7QIcNC', 'admin@example.com', 1);
-- 实际运行前请执行以下 Python 生成正确的 hash：
--   import bcrypt
--   print(bcrypt.hashpw(b"admin123"[:72], bcrypt.gensalt()).decode())


-- ============================================================================
-- 验证：查看表结构
-- ============================================================================
-- SHOW TABLES;
-- DESCRIBE users;
-- DESCRIBE chat_history;
-- DESCRIBE knowledge_docs;

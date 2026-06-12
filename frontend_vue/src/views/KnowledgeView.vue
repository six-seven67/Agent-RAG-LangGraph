<template>
  <div class="knowledge-page">
    <h1>📚 知识库管理</h1>
    <p class="page-desc">上传文档构建您的专属知识库，AI 将基于这些资料回答问题</p>

    <!-- Upload Zone -->
    <div class="upload-zone" :class="{ dragover }"
         @click="triggerFile"
         @dragover.prevent="dragover = true"
         @dragleave="dragover = false"
         @drop.prevent="onDrop">
      <div class="upload-icon">📁</div>
      <p><strong>点击选择文件</strong> 或将文件拖拽到此处</p>
      <p class="hint">单文件最大 10 MB</p>
      <div class="format-badges">
        <span class="format-badge file-txt">.txt 文本</span>
        <span class="format-badge file-pdf">.pdf 文档</span>
        <span class="format-badge file-docx">.docx 文档</span>
        <span class="format-badge file-xlsx">.xlsx 表格</span>
      </div>
      <input type="file" ref="fileInput" accept=".txt,.pdf,.docx,.xlsx" hidden
             @change="onFileSelect">

      <!-- Upload progress -->
      <div v-if="uploading" class="upload-progress">
        <div class="upload-progress-bar"><div class="fill"></div></div>
        <span style="font-size:0.8rem;color:var(--color-text-muted)">{{ uploadingText }}</span>
      </div>
      <div v-else-if="uploadStatus" class="mt-sm" :style="{ color: uploadStatus.color }">
        {{ uploadStatus.text }}
      </div>
    </div>

    <!-- Toolbar -->
    <div class="doc-toolbar">
      <span class="doc-count">{{ docs.length > 0 ? `共 ${docs.length} 个文档` : '' }}</span>
    </div>

    <!-- Document Table -->
    <div class="doc-table-wrapper">
      <table class="doc-table">
        <thead>
          <tr>
            <th class="col-name">文件名</th>
            <th class="col-hash">MD5</th>
            <th class="col-chunks">分块数</th>
            <th class="col-time">上传时间</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <!-- Skeleton loading -->
          <template v-if="loading">
            <tr v-for="n in 4" :key="'sk-'+n">
              <td><div class="skeleton" style="width:180px;height:16px"></div></td>
              <td><div class="skeleton" style="width:120px;height:14px"></div></td>
              <td><div class="skeleton" style="width:40px;height:14px;margin:0 auto"></div></td>
              <td><div class="skeleton" style="width:130px;height:14px"></div></td>
              <td><div class="skeleton" style="width:50px;height:14px;margin:0 auto"></div></td>
            </tr>
          </template>

          <!-- Empty -->
          <tr v-else-if="docs.length === 0">
            <td colspan="5" class="doc-table-empty">
              <div style="font-size:2.5rem;margin-bottom:0.5rem;opacity:.5">📄</div>
              暂无文档，上传文件开始构建知识库吧
            </td>
          </tr>

          <!-- Rows -->
          <tr v-for="doc in docs" :key="doc.id">
            <td>
              <span class="file-icon" :class="fileIconClass(doc.filename)">{{ fileIcon(doc.filename) }}</span>
              <strong>{{ doc.filename }}</strong>
            </td>
            <td class="text-secondary">
              <code style="font-size:0.75rem">{{ (doc.md5_hash || '').substring(0, 16) }}...</code>
            </td>
            <td class="text-secondary" style="text-align:center">{{ doc.chunk_count }}</td>
            <td class="text-secondary">{{ formatDate(doc.created_at) }}</td>
            <td style="text-align:center">
              <button class="btn btn-sm btn-outline" style="margin-right:0.25rem"
                      @click="previewDoc(doc)" title="预览内容">
                👁
              </button>
              <button class="btn btn-sm btn-outline btn-del-doc"
                      @click="handleDelete(doc)" title="删除">
                🗑
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Preview Modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="previewOpen" class="modal-overlay" @click.self="previewOpen = false">
          <div class="modal-content">
            <div class="modal-header">
              <h3>{{ previewTitle }}</h3>
              <button class="btn-icon" @click="previewOpen = false" style="font-size:1.2rem">✕</button>
            </div>
            <div class="modal-body">
              <div v-if="previewLoading" style="text-align:center;padding:2rem;color:var(--color-text-muted)">
                加载中...
              </div>
              <div v-else>{{ previewContent }}</div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useToastStore } from '../stores/toast.js'
import * as API from '../api/index.js'
import { formatDate, checkFileExt } from '../utils/helpers.js'

const toast = useToastStore()
const docs = ref([])
const loading = ref(true)
const dragover = ref(false)
const uploadStatus = ref(null)
const uploading = ref(false)
const uploadingText = ref('')
const fileInput = ref(null)

// Preview state
const previewOpen = ref(false)
const previewTitle = ref('')
const previewContent = ref('')
const previewLoading = ref(false)

onMounted(() => { loadDocuments() })

async function loadDocuments() {
  loading.value = true
  try {
    const data = await API.getDocuments()
    docs.value = data.documents || []
  } catch (err) {
    toast.error(err.message)
  } finally {
    loading.value = false
  }
}

function triggerFile() {
  fileInput.value?.click()
}

function fileIcon(filename) {
  const ext = (filename || '').toLowerCase().split('.').pop()
  const map = { txt: '📝', pdf: '📕', docx: '📘', xlsx: '📗' }
  return map[ext] || '📎'
}

function fileIconClass(filename) {
  const ext = (filename || '').toLowerCase().split('.').pop()
  return 'file-' + ext
}

async function handleUpload(file) {
  if (!checkFileExt(file.name)) {
    toast.error('仅支持 TXT / PDF / DOCX / XLSX 格式文件')
    return
  }
  uploading.value = true
  uploadingText.value = `⏳ 正在上传「${file.name}」...`
  uploadStatus.value = null

  try {
    const result = await API.uploadDocument(file)
    uploading.value = false
    uploadStatus.value = { text: `✅ ${result.message}（共 ${result.chunk_count} 个语义块）`, color: 'var(--color-success)' }
    toast.success(`上传成功，共 ${result.chunk_count} 个语义块`)
    loadDocuments()
  } catch (err) {
    uploading.value = false
    uploadStatus.value = { text: `❌ ${err.message}`, color: 'var(--color-danger)' }
    toast.error(err.message)
  }
  setTimeout(() => { uploadStatus.value = null }, 5000)
}

function onFileSelect(e) {
  if (e.target.files.length > 0) {
    handleUpload(e.target.files[0])
    e.target.value = ''
  }
}

function onDrop(e) {
  dragover.value = false
  const file = e.dataTransfer.files[0]
  if (file) handleUpload(file)
}

async function handleDelete(doc) {
  if (!confirm(`确定删除文档「${doc.filename}」？\n此操作不可撤销，将从数据库和向量库中永久移除。`)) return
  try {
    await API.deleteDocument(doc.id)
    toast.success(`文档「${doc.filename}」已删除`)
    loadDocuments()
  } catch (err) {
    toast.error(err.message)
  }
}

async function previewDoc(doc) {
  previewOpen.value = true
  previewTitle.value = doc.filename
  previewLoading.value = true
  previewContent.value = ''
  try {
    // Fetch the original file as text for preview
    const res = await API.getDocumentPreview(doc.id)
    previewContent.value = res.content || '(无文本内容)'
  } catch (err) {
    previewContent.value = `❌ 预览失败: ${err.message}`
  } finally {
    previewLoading.value = false
  }
}
</script>

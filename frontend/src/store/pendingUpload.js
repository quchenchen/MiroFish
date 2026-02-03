/**
 * 临时存储待上传的文件和需求
 * 用于首页点击启动引擎后立即跳转，在Process页面再进行API调用
 * 支持 sessionStorage 持久化，刷新页面后不会丢失数据
 */
import { reactive } from 'vue'
import { saveSessionState, getSessionState, clearSessionState, STATE_KEYS } from './sessionState'

const STORAGE_KEY_FILES = STATE_KEYS.PENDING_FILES
const STORAGE_KEY_REQUIREMENT = STATE_KEYS.PENDING_REQUIREMENT

// 从 sessionStorage 恢复初始状态
const savedFiles = getSessionState(STORAGE_KEY_FILES, [])
const savedRequirement = getSessionState(STORAGE_KEY_REQUIREMENT, '')

const state = reactive({
  files: savedFiles,
  simulationRequirement: savedRequirement,
  isPending: savedFiles.length > 0
})

export function setPendingUpload(files, requirement) {
  state.files = files
  state.simulationRequirement = requirement
  state.isPending = true

  // 持久化到 sessionStorage
  // 注意：File 对象无法直接序列化，只保存文件基本信息
  const fileInfos = files.map(f => ({
    name: f.name,
    size: f.size,
    type: f.type,
    // 保存原始 File 对象的引用（内存中）
    _fileRef: f
  }))
  saveSessionState(STORAGE_KEY_FILES, fileInfos)
  saveSessionState(STORAGE_KEY_REQUIREMENT, requirement)
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    isPending: state.isPending
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.isPending = false

  // 清除 sessionStorage
  clearSessionState(STORAGE_KEY_FILES)
  clearSessionState(STORAGE_KEY_REQUIREMENT)
}

// 恢复文件（用于刷新页面后重新获取 File 对象）
// 用户需要重新选择文件，这里提供提示信息
export function getRestorableFileInfo() {
  const fileInfos = getSessionState(STORAGE_KEY_FILES, [])
  const requirement = getSessionState(STORAGE_KEY_REQUIREMENT, '')
  return {
    hasPendingData: fileInfos.length > 0,
    fileCount: fileInfos.length,
    fileNames: fileInfos.map(f => f.name),
    requirement: requirement
  }
}

export default state

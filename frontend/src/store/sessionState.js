/**
 * Session State Management
 * 用于在页面刷新后持久化关键状态
 */

const STORAGE_PREFIX = 'mirofish_'

// 保存数据到 sessionStorage
export function saveSessionState(key, value) {
  try {
    const fullKey = STORAGE_PREFIX + key
    if (value === null || value === undefined) {
      sessionStorage.removeItem(fullKey)
    } else {
      sessionStorage.setItem(fullKey, JSON.stringify(value))
    }
  } catch (e) {
    console.warn('Failed to save session state:', key, e)
  }
}

// 从 sessionStorage 获取数据
export function getSessionState(key, defaultValue = null) {
  try {
    const fullKey = STORAGE_PREFIX + key
    const item = sessionStorage.getItem(fullKey)
    if (item === null) return defaultValue
    return JSON.parse(item)
  } catch (e) {
    console.warn('Failed to get session state:', key, e)
    return defaultValue
  }
}

// 清除指定 key
export function clearSessionState(key) {
  try {
    const fullKey = STORAGE_PREFIX + key
    sessionStorage.removeItem(fullKey)
  } catch (e) {
    console.warn('Failed to clear session state:', key, e)
  }
}

// 清除所有 mirofish 相关的 session state
export function clearAllSessionState() {
  try {
    const keys = Object.keys(sessionStorage)
    keys.forEach(key => {
      if (key.startsWith(STORAGE_PREFIX)) {
        sessionStorage.removeItem(key)
      }
    })
  } catch (e) {
    console.warn('Failed to clear all session state:', e)
  }
}

// ========== 预定义的 State Keys ==========
export const STATE_KEYS = {
  CURRENT_PROJECT_ID: 'current_project_id',
  CURRENT_SIMULATION_ID: 'current_simulation_id',
  CURRENT_STEP: 'current_step',
  CURRENT_PHASE: 'current_phase',
  SYSTEM_LOGS: 'system_logs',
  VIEW_MODE: 'view_mode',
  PENDING_FILES: 'pending_files',
  PENDING_REQUIREMENT: 'pending_requirement',
  LAST_ROUTE: 'last_route'
}

// ========== 便捷函数 ==========
export function saveCurrentProjectId(projectId) {
  saveSessionState(STATE_KEYS.CURRENT_PROJECT_ID, projectId)
}

export function getCurrentProjectId() {
  return getSessionState(STATE_KEYS.CURRENT_PROJECT_ID)
}

export function saveCurrentSimulationId(simulationId) {
  saveSessionState(STATE_KEYS.CURRENT_SIMULATION_ID, simulationId)
}

export function getCurrentSimulationId() {
  return getSessionState(STATE_KEYS.CURRENT_SIMULATION_ID)
}

export function saveSystemLogs(logs) {
  saveSessionState(STATE_KEYS.SYSTEM_LOGS, logs)
}

export function getSystemLogs() {
  return getSessionState(STATE_KEYS.SYSTEM_LOGS, [])
}

export function saveViewMode(viewMode) {
  saveSessionState(STATE_KEYS.VIEW_MODE, viewMode)
}

export function getViewMode() {
  return getSessionState(STATE_KEYS.VIEW_MODE, 'split')
}

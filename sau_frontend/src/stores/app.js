import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  // 是否是第一次进入账号管理页面
  const isFirstTimeAccountManagement = ref(true)
  
  // 是否是第一次进入素材管理页面
  const isFirstTimeMaterialManagement = ref(true)

  // 账号管理页面刷新状态
  const isAccountRefreshing = ref(false)

  // 素材列表数据
  const materials = ref([])
  const publishedMaterials = ref([])
  const listCache = ref({})
  
  // 设置账号管理页面已访问
  const setAccountManagementVisited = () => {
    isFirstTimeAccountManagement.value = false
  }
  
  // 设置素材管理页面已访问
  const setMaterialManagementVisited = () => {
    isFirstTimeMaterialManagement.value = false
  }
  
  // 重置所有访问状态（用于重新登录或刷新应用时）
  const resetVisitStatus = () => {
    isFirstTimeAccountManagement.value = true
    isFirstTimeMaterialManagement.value = true
  }

  // 更新素材列表
  const setMaterials = (materialList) => {
    materials.value = materialList
  }

  const setPublishedMaterials = (materialList) => {
    publishedMaterials.value = materialList
  }

  // 添加新素材
  const addMaterial = (material) => {
    materials.value.push(material)
  }

  // 删除素材
  const removeMaterial = (materialId) => {
    const index = materials.value.findIndex(m => m.id === materialId)
    if (index > -1) {
      materials.value.splice(index, 1)
    }
  }

  const removeMaterials = (materialIds) => {
    const idSet = new Set(materialIds.map(id => String(id)))
    materials.value = materials.value.filter(m => !idSet.has(String(m.id)))
  }

  const getListCache = (key, maxAgeMs = 60000) => {
    const cached = listCache.value[key]
    if (!cached) return null
    if (Date.now() - cached.loadedAt > maxAgeMs) return null
    return cached.payload
  }

  const setListCache = (key, payload) => {
    listCache.value = {
      ...listCache.value,
      [key]: {
        payload,
        loadedAt: Date.now()
      }
    }
  }

  const clearListCache = (prefix = '') => {
    if (!prefix) {
      listCache.value = {}
      return
    }
    listCache.value = Object.fromEntries(
      Object.entries(listCache.value).filter(([key]) => !key.startsWith(prefix))
    )
  }
  
  // 设置账号管理页面刷新状态
  const setAccountRefreshing = (status) => {
    isAccountRefreshing.value = status
  }

  return {
    isFirstTimeAccountManagement,
    isFirstTimeMaterialManagement,
    isAccountRefreshing,
    materials,
    publishedMaterials,
    listCache,
    setAccountManagementVisited,
    setMaterialManagementVisited,
    resetVisitStatus,
    setMaterials,
    setPublishedMaterials,
    addMaterial,
    removeMaterial,
    removeMaterials,
    getListCache,
    setListCache,
    clearListCache,
    setAccountRefreshing
  }
})

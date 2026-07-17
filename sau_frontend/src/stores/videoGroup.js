import { defineStore } from 'pinia'
import { ref } from 'vue'
import { youtubeApi } from '@/api/youtube'
import { useAppStore } from '@/stores/app'

export const useVideoGroupStore = defineStore('videoGroup', () => {
  const groups = ref([])
  const defaultGroupId = ref(null)
  const loading = ref(false)
  let loaded = false

  const invalidateRelatedCaches = () => {
    const appStore = useAppStore()
    appStore.clearListCache('youtube:videos:')
    appStore.clearListCache('materials:')
    appStore.clearListCache('publish:center:materials:')
  }

  const load = async ({ force = false } = {}) => {
    if (loaded && !force) return groups.value
    loading.value = true
    try {
      const response = await youtubeApi.getVideoGroups()
      groups.value = response.data?.items || []
      defaultGroupId.value = response.data?.defaultGroupId ?? null
      loaded = true
      return groups.value
    } finally {
      loading.value = false
    }
  }

  const refreshAfterMutation = async () => {
    invalidateRelatedCaches()
    return load({ force: true })
  }

  const create = async (name) => {
    await youtubeApi.createVideoGroup({ name })
    return refreshAfterMutation()
  }

  const rename = async (groupId, name) => {
    await youtubeApi.renameVideoGroup(groupId, { name })
    return refreshAfterMutation()
  }

  const remove = async (groupId) => {
    const response = await youtubeApi.deleteVideoGroup(groupId)
    await refreshAfterMutation()
    return response.data || {}
  }

  const moveVideos = async (videoIds, groupId) => {
    const response = await youtubeApi.moveVideosToGroup({ videoIds, groupId })
    invalidateRelatedCaches()
    await load({ force: true })
    return response.data || {}
  }

  return { groups, defaultGroupId, loading, load, create, rename, remove, moveVideos, invalidateRelatedCaches }
})

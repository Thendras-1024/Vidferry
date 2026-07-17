<template>
  <el-dialog :model-value="modelValue" title="管理线索分组" width="520px" @update:model-value="$emit('update:modelValue', $event)">
    <div class="group-create-row">
      <el-input v-model="newGroupName" maxlength="30" placeholder="输入新分组名称" @keyup.enter="createGroup" />
      <el-button type="primary" :loading="saving" @click="createGroup">
        <el-icon><Plus /></el-icon>
        新建
      </el-button>
    </div>

    <div class="group-list" v-loading="videoGroupStore.loading">
      <div v-for="group in videoGroupStore.groups" :key="group.id" class="group-row">
        <div class="group-main">
          <strong>{{ group.name }}</strong>
          <el-tag v-if="group.isDefault" size="small" type="info">默认</el-tag>
          <span>{{ group.videoCount }} 条线索</span>
        </div>
        <div v-if="!group.isDefault" class="group-actions">
          <el-button text :icon="Edit" title="重命名分组" @click="renameGroup(group)" />
          <el-button text type="danger" :icon="Delete" title="删除分组" @click="deleteGroup(group)" />
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { Delete, Edit, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useVideoGroupStore } from '@/stores/videoGroup'

defineProps({ modelValue: { type: Boolean, default: false } })
defineEmits(['update:modelValue', 'changed'])

const videoGroupStore = useVideoGroupStore()
const newGroupName = ref('')
const saving = ref(false)

const createGroup = async () => {
  const name = newGroupName.value.trim()
  if (!name) return ElMessage.warning('请输入分组名称')
  saving.value = true
  try {
    await videoGroupStore.create(name)
    newGroupName.value = ''
    ElMessage.success('分组已创建')
  } finally {
    saving.value = false
  }
}

const renameGroup = async (group) => {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的分组名称', '重命名分组', {
      inputValue: group.name,
      inputValidator: value => Boolean(String(value || '').trim()) || '分组名称不能为空',
      inputErrorMessage: '分组名称不能为空'
    })
    await videoGroupStore.rename(group.id, value)
    ElMessage.success('分组已重命名')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') console.warn('重命名分组失败:', error)
  }
}

const deleteGroup = async (group) => {
  try {
    await ElMessageBox.confirm(
      `删除分组“${group.name}”后，其中 ${group.videoCount} 条线索将移到默认分组。`,
      '删除分组',
      { type: 'warning', confirmButtonText: '删除并移动', cancelButtonText: '取消' }
    )
    await videoGroupStore.remove(group.id)
    ElMessage.success('分组已删除，线索已移到默认分组')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') console.warn('删除分组失败:', error)
  }
}
</script>

<style scoped>
.group-create-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; margin-bottom: 16px; }
.group-list { display: grid; gap: 8px; min-height: 80px; }
.group-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border: 1px solid #e4e9f0; border-radius: 8px; }
.group-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.group-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.group-main span { color: #7b8799; font-size: 12px; }
.group-actions { display: flex; align-items: center; }
@media (max-width: 560px) { .group-create-row { grid-template-columns: 1fr; } }
</style>

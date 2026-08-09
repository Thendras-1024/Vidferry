<template>
  <el-select
    :model-value="modelValue"
    :loading="videoGroupStore.loading"
    :placeholder="resolvedPlaceholder"
    :clearable="includeAll"
    filterable
    @update:model-value="$emit('update:modelValue', $event ?? '')"
  >
    <el-option v-if="includeAll" label="全部分组" value="" />
    <el-option
      v-for="group in videoGroupStore.groups"
      :key="group.id"
      :label="group.name"
      :value="group.id"
    >
      <span class="group-option-name">{{ group.name }}</span>
      <span class="group-option-count">{{ group.videoCount }} 条</span>
    </el-option>
  </el-select>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useVideoGroupStore } from '@/stores/videoGroup'

const props = defineProps({
  modelValue: { type: [Number, String], default: '' },
  includeAll: { type: Boolean, default: false },
  placeholder: { type: String, default: '' }
})

defineEmits(['update:modelValue'])

const videoGroupStore = useVideoGroupStore()
const resolvedPlaceholder = computed(() => props.placeholder || (props.includeAll ? '全部分组' : '选择线索分组'))

onMounted(() => videoGroupStore.load())
</script>

<style scoped>
.group-option-name { font-weight: 600; color: var(--vf-text-primary); }
.group-option-count { float: right; color: #7b8799; font-size: 12px; }
</style>

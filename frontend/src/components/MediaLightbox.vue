<template>
  <div
    class="fixed inset-0 bg-black bg-opacity-90 z-50 flex items-center justify-center"
    @click="$emit('close')"
  >
    <div class="relative max-w-[90vw] max-h-[90vh]">
      <img
        :src="src"
        class="max-w-full max-h-[90vh] object-contain"
        @click.stop
      />
      <button
        @click="$emit('close')"
        class="absolute top-4 right-4 w-10 h-10 bg-white bg-opacity-20 rounded-full flex items-center justify-center text-white text-2xl hover:bg-opacity-30"
      >
        ×
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { defineProps, defineEmits } from 'vue'

defineProps<{
  src: string
}>()

defineEmits<{
  close: []
}>()
</script>
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiClient } from '../api/client'
import type { SearchHit } from '../api/types'

export const useSearchStore = defineStore('search', () => {
  const keyword = ref('')
  const searchResults = ref<SearchHit[]>([])
  const searching = ref(false)
  let debounceTimer: number

  async function doSearch() {
    if (!keyword.value.trim()) {
      searchResults.value = []
      return
    }
    searching.value = true
    try {
      searchResults.value = await apiClient.search({ q: keyword.value, limit: 50 })
    } catch (e) {
      console.error('search error', e)
      searchResults.value = []
    } finally {
      searching.value = false
    }
  }

  function handleSearch() {
    clearTimeout(debounceTimer)
    debounceTimer = window.setTimeout(doSearch, 300)
  }

  return { keyword, searchResults, searching, doSearch, handleSearch }
})
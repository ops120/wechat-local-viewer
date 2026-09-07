import { createRouter, createWebHashHistory } from 'vue-router'
import Home from './views/Home.vue'
import Chat from './views/Chat.vue'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Home },
    { path: '/c/:username', component: Chat },
  ],
})
<template>
  <Navbar v-if="showNavbar" @toggle-sidebar="sidebarOpen = !sidebarOpen" />
  <router-view v-slot="{ Component }">
    <Transition name="page" mode="out-in">
      <component :is="Component" :sidebar-open="sidebarOpen" @close-sidebar="sidebarOpen = false" />
    </Transition>
  </router-view>
  <ToastContainer />
  <CommandPalette />
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import Navbar from './components/Navbar.vue'
import ToastContainer from './components/ToastContainer.vue'
import CommandPalette from './components/CommandPalette.vue'
import { useKeyboard } from './composables/useKeyboard.js'

const route = useRoute()
const sidebarOpen = ref(false)
const showNavbar = computed(() => !['/login', '/register'].includes(route.path))

useKeyboard()

// Close sidebar on route change
import { watch } from 'vue'
watch(() => route.path, () => { sidebarOpen.value = false })
</script>

import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import './style.css'
import App from './App.vue'
import Dashboard from './views/Dashboard.vue'
import NewProject from './views/NewProject.vue'
import ProjectView from './views/ProjectView.vue'
import Library from './views/Library.vue'
import Settings from './views/Settings.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Dashboard, meta: { title: 'Painel' } },
    { path: '/novo', component: NewProject, meta: { title: 'Criar Shorts' } },
    { path: '/projetos/:id', component: ProjectView, props: true, meta: { title: 'Projeto' } },
    { path: '/biblioteca', component: Library, meta: { title: 'Biblioteca' } },
    { path: '/configuracoes', component: Settings, meta: { title: 'Configurações' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = `${to.meta.title || ''} · ClipFlow Studio`
})

createApp(App).use(router).mount('#app')

import tailwindcss from '@tailwindcss/vite'

// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  future: { compatibilityVersion: 4 },
  devtools: { enabled: false },
  modules: ['@nuxt/eslint'],
  // standalone:false → Nuxt doesn't bundle its own copy of shared plugins
  // (import, etc.); it composes with antfu's instead. See eslint.nuxt.com.
  eslint: {
    config: { standalone: false },
  },
  css: ['~/assets/css/main.css'],
  vite: {
    plugins: [tailwindcss()],
  },
  app: {
    head: {
      title: 'degen · gauges',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'robots', content: 'noindex, nofollow' },
      ],
    },
  },
  nitro: {
    // node:sqlite is a Node built-in; keep it external so Nitro doesn't bundle it.
    externals: { external: ['node:sqlite'] },
  },
})

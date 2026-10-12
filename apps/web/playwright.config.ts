import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests/e2e',use:{baseURL:'http://localhost:3000'},
  workers:1,reporter:'list',timeout:30000});

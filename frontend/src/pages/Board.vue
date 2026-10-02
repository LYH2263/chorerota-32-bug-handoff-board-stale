<template>
  <div>
    <h1 class="brand">本周看板</h1>
    <p class="muted">周卡片网格 · round-robin 落位后可去「对调」申请交换</p>
    <div style="display:flex;gap:8px;margin:12px 0">
      <button @click="generate">生成周表</button>
      <button class="ghost" @click="load">刷新</button>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <section v-if="handovers.length" class="week-card" style="margin-bottom:12px">
      <header>移交清单</header>
      <div v-for="h in handovers" :key="h.id" style="margin-bottom:6px">
        <span class="chip coral">{{ h.from_name }}</span> →
        <span class="chip">{{ h.to_name }}</span>
        <span class="chip" :class="{ coral: h.status === 'issued' }">{{ h.status }}</span>
        <span class="muted"> · {{ h.cell_count }} 格</span>
        <div>
          <span v-for="c in h.cells" :key="c.day + '-' + c.task_id" class="chip">
            D{{ c.day }} · {{ c.task_title }}
          </span>
        </div>
      </div>
    </section>
    <div class="week-grid">
      <article v-for="d in days" :key="d" class="week-card">
        <header>Day {{ d }}</header>
        <div v-for="a in byDay(d)" :key="a.id">
          <span class="chip">{{ a.task_title }}</span>
          <span class="chip coral">{{ a.member_name }}</span>
        </div>
        <p v-if="!byDay(d).length" class="muted">空</p>
      </article>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const assigns = ref([])
const handovers = ref([])
const days = [0,1,2,3,4,5,6]
const err = ref('')
const weekId = 1
function byDay(d) { return assigns.value.filter(a => a.day === d) }
async function load() {
  err.value = ''
  try {
    const b = await api('/weeks/' + weekId + '/board')
    assigns.value = b.assignments || []
    handovers.value = b.handovers || []
  } catch (e) { err.value = e.message }
}
async function generate() {
  err.value = ''
  try { await api('/weeks/' + weekId + '/generate', { method: 'POST', body: '{}' }); await load() }
  catch (e) { err.value = e.message }
}
onMounted(load)
</script>

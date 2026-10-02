<template>
  <div>
    <h1 class="brand">成员</h1>
    <form @submit.prevent="add">
      <input v-model="name" placeholder="新成员姓名" />
      <button type="submit">添加</button>
    </form>
    <ul class="list">
      <li v-for="m in rows" :key="m.id">
        <strong>{{ m.name }}</strong>
        <span class="muted"> · {{ m.active ? '在岗' : '停用' }} · {{ m.data_quality }}</span>
        <button v-if="m.active" class="ghost" style="margin-left:8px" @click="open(m)">交接停用</button>
      </li>
    </ul>

    <div v-if="panel" class="week-card" style="margin-top:16px">
      <header>离场交接 · {{ panel.name }}</header>
      <label>接收人
        <select v-model.number="toId">
          <option :value="0" disabled>选择接收人</option>
          <option v-for="m in rows.filter(x => x.id !== panel.id)" :key="m.id" :value="m.id">
            {{ m.name }}（{{ m.active ? '在岗' : '停用' }} · {{ m.data_quality }}）
          </option>
        </select>
      </label>
      <label>交接周
        <select v-model.number="weekId">
          <option v-for="w in weeks" :key="w.id" :value="w.id">{{ w.label }}</option>
        </select>
      </label>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="ghost" :disabled="!toId" @click="preview">预览交接</button>
        <button class="ghost" :disabled="!toId" @click="issue">签发交接条</button>
        <button :disabled="!handover" @click="confirm">确认交接</button>
        <button :disabled="!confirmed" @click="deactivate">停用成员</button>
        <button class="ghost" @click="panel = null">取消</button>
      </div>
      <p v-if="err" class="err">{{ err }}</p>
      <p v-if="msg" class="muted">{{ msg }}</p>
      <div v-if="cells.length">
        <p class="muted">{{ cellsTitle }}</p>
        <span v-for="c in cells" :key="c.day + '-' + c.task_id" class="chip">
          D{{ c.day }} · {{ c.task_title }}
        </span>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const rows = ref([])
const weeks = ref([])
const name = ref('')
const panel = ref(null)
const toId = ref(0)
const weekId = ref(1)
const handover = ref(null)
const confirmed = ref(false)
const cells = ref([])
const cellsTitle = ref('')
const err = ref('')
const msg = ref('')

async function load() { rows.value = await api('/members') }
async function add() {
  if (!name.value.trim()) return
  await api('/members', { method: 'POST', body: JSON.stringify({ name: name.value }) })
  name.value = ''; await load()
}
async function open(m) {
  if (!weeks.value.length) weeks.value = await api('/weeks')
  panel.value = m; toId.value = 0; weekId.value = weeks.value[0]?.id || 1
  handover.value = null; confirmed.value = false; cells.value = []
  err.value = ''; msg.value = ''
}
async function run(fn) {
  err.value = ''; msg.value = ''
  try { await fn() } catch (e) { err.value = e.message }
}
function preview() {
  return run(async () => {
    const r = await api(`/weeks/${weekId.value}/handovers/preview`, {
      method: 'POST',
      body: JSON.stringify({ from_member_id: panel.value.id, to_member_id: toId.value }),
    })
    cells.value = r.cells
    cellsTitle.value = `将被接管 ${r.count} 格（预览，未改库）`
  })
}
function issue() {
  return run(async () => {
    handover.value = await api(`/weeks/${weekId.value}/handovers`, {
      method: 'POST',
      body: JSON.stringify({ from_member_id: panel.value.id, to_member_id: toId.value }),
    })
    msg.value = `已签发交接条 #${handover.value.id}，待确认`
  })
}
function confirm() {
  return run(async () => {
    const r = await api(`/handovers/${handover.value.id}/confirm`, { method: 'POST', body: '{}' })
    confirmed.value = true
    cells.value = r.handover.cells
    cellsTitle.value = `已移交 ${r.transferred} 格`
    msg.value = `交接确认：${r.handover.from_name} → ${r.handover.to_name}，作废对调 ${r.voided_swaps.length} 条`
  })
}
function deactivate() {
  return run(async () => {
    await api(`/members/${panel.value.id}/deactivate`, {
      method: 'POST', body: JSON.stringify({ week_id: weekId.value }),
    })
    panel.value = null
    await load()
  })
}
onMounted(load)
</script>

<!-- handoff board lag soft fork -->

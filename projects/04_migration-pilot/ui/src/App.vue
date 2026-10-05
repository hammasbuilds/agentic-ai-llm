<script setup>
import { ref, computed } from "vue";

/*
 * The UI's one job is to make the two classes of edit impossible to confuse.
 * Mechanical edits get an "Apply" affordance; behavioural ones get an
 * explanation and no button at all, because there is no safe automatic
 * action for them.
 */

const path = ref("C:\\src");
const busy = ref(false);
const error = ref("");
const result = ref(null);
const showSafeOnly = ref(false);

const files = computed(() => {
  if (!result.value) return [];
  if (!showSafeOnly.value) return result.value.files;
  return result.value.files
    .map((f) => ({ ...f, edits: f.edits.filter((e) => e.mechanical) }))
    .filter((f) => f.edits.length);
});

async function scan() {
  busy.value = true;
  error.value = "";
  result.value = null;
  try {
    const response = await fetch(`/api/scan?path=${encodeURIComponent(path.value)}`);
    const payload = await response.json();
    if (payload.error) error.value = payload.error;
    else result.value = payload;
  } catch (err) {
    error.value = String(err);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main>
    <header>
      <h1>migration-pilot</h1>
      <p class="sub">
        Modernises Python where the rewrite is provably equivalent, and refuses where it
        would change what the program does. Every deprecation fix is not a rename.
      </p>
    </header>

    <div class="row">
      <input v-model="path" placeholder="file or folder" @keyup.enter="scan" />
      <button :disabled="busy" @click="scan">{{ busy ? "Scanning…" : "Scan" }}</button>
      <label class="toggle">
        <input v-model="showSafeOnly" type="checkbox" />
        only show what can be applied automatically
      </label>
    </div>

    <p v-if="error" class="err">{{ error }}</p>

    <template v-if="result">
      <div class="stats">
        <div class="stat">
          <div class="v">{{ result.files_scanned.toLocaleString() }}</div>
          <div class="k">files scanned</div>
        </div>
        <div class="stat ok">
          <div class="v">{{ result.mechanical }}</div>
          <div class="k">mechanical — safe to apply</div>
        </div>
        <div class="stat warn">
          <div class="v">{{ result.behavioural }}</div>
          <div class="k">behavioural — never auto-applied</div>
        </div>
        <div class="stat">
          <div class="v">{{ result.parse_errors }}</div>
          <div class="k">files that did not parse</div>
        </div>
      </div>

      <p v-if="result.behavioural > result.mechanical" class="callout">
        More of what this scan found changes behaviour than does not. A tool that
        auto-fixed every deprecation would be making semantic changes most of the time.
      </p>

      <section v-for="file in files" :key="file.path" class="file">
        <h2>{{ file.path }}</h2>
        <div v-for="(edit, i) in file.edits" :key="i" class="edit" :class="edit.mechanical ? 'auto' : 'review'">
          <div class="head">
            <span class="pill" :class="edit.mechanical ? 'auto' : 'review'">
              {{ edit.mechanical ? "auto" : "review" }}
            </span>
            <span class="rule">{{ edit.rule }}</span>
            <span class="loc">line {{ edit.line }}</span>
          </div>
          <div class="change">
            <code class="before">{{ edit.before }}</code>
            <span class="arrow">→</span>
            <code class="after">{{ edit.replacement }}</code>
          </div>
          <p v-if="!edit.mechanical" class="why">{{ edit.note }}</p>
        </div>
      </section>

      <p v-if="!files.length" class="empty">Nothing to change.</p>
    </template>
  </main>
</template>

<style scoped>
main { max-width: 1000px; margin: 0 auto; padding-block: 2rem 4rem; padding-inline: 20px; }
h1 { font-size: 1.2rem; margin: 0 0 0.3rem; }
.sub { color: var(--muted); font-size: 0.88rem; margin: 0 0 1.5rem; max-width: 64ch; }
.row { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; margin-bottom: 1.5rem; }
input[type="text"], input:not([type]) { flex: 1; min-width: 16rem; font: inherit;
  padding: 0.45rem 0.7rem; border-radius: 8px; border: 1px solid var(--line);
  background: var(--panel); color: var(--ink); }
button { font: inherit; padding: 0.45rem 1rem; border-radius: 8px; border: none;
  background: var(--accent); color: #fff; cursor: pointer; }
button:disabled { opacity: 0.5; cursor: default; }
.toggle { display: flex; align-items: center; gap: 0.4rem; font-size: 0.84rem; color: var(--muted); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.7rem; margin-bottom: 1.25rem; }
.stat { border: 1px solid var(--line); border-radius: 10px; padding: 0.85rem; background: var(--panel); }
.stat.ok { border-left: 3px solid var(--good); }
.stat.warn { border-left: 3px solid var(--warn); }
.stat .v { font-size: 1.5rem; font-weight: 650; }
.stat .k { font-size: 0.74rem; color: var(--muted); }
.callout { border: 1px solid var(--line); border-left: 3px solid var(--warn);
  border-radius: 8px; padding: 0.8rem 1rem; background: var(--panel);
  font-size: 0.88rem; margin-bottom: 1.5rem; }
.file { margin-bottom: 1.5rem; }
h2 { font-size: 0.78rem; font-family: var(--mono); color: var(--muted);
  margin: 0 0 0.5rem; word-break: break-all; }
.edit { border: 1px solid var(--line); border-radius: 8px; padding: 0.6rem 0.8rem;
  background: var(--panel); margin-bottom: 0.5rem; }
.edit.review { border-left: 3px solid var(--warn); }
.edit.auto { border-left: 3px solid var(--good); }
.head { display: flex; gap: 0.6rem; align-items: center; font-size: 0.78rem; margin-bottom: 0.35rem; }
.pill { padding: 0.06rem 0.45rem; border-radius: 999px; font-size: 0.66rem;
  font-weight: 650; text-transform: uppercase; }
.pill.auto { background: color-mix(in srgb, var(--good) 18%, transparent); color: var(--good); }
.pill.review { background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }
.rule { font-family: var(--mono); }
.loc { color: var(--muted); margin-left: auto; }
.change { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; font-size: 0.84rem; }
code { font-family: var(--mono); font-size: 0.85em; }
.before { color: var(--fail); }
.after { color: var(--good); }
.arrow { color: var(--muted); }
.why { color: var(--muted); font-size: 0.82rem; margin: 0.45rem 0 0; }
.err { color: var(--fail); }
.empty { color: var(--muted); }
</style>

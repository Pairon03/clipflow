// Escolhas de edição salvas como padrão (aba "Preferências") <-> formulário de "Criar Shorts".
export const DURATION_PRESETS = { '15-30': [15, 30], '30-60': [30, 60], '60-90': [60, 90] }
export const COUNT_PRESETS = [3, 5, 10]

const KEYS = ['caption_style', 'layout', 'pace', 'speed', 'cold_open', 'title_style', 'title_duration',
  'title_position', 'color_filter', 'transition', 'zoom_fx', 'flip_fx', 'sfx', 'censor', 'engine', 'hook', 'zoom', 'series']

export function applyPreferences(form, prefs) {
  if (!prefs) return
  for (const k of KEYS) if (prefs[k] !== undefined) form[k] = prefs[k]
  if (prefs.count) {
    if (COUNT_PRESETS.includes(prefs.count)) form.count = prefs.count
    else { form.count = 'custom'; form.customCount = prefs.count }
  }
  if (prefs.min_duration && prefs.max_duration) {
    const key = Object.keys(DURATION_PRESETS)
      .find((k) => DURATION_PRESETS[k][0] === prefs.min_duration && DURATION_PRESETS[k][1] === prefs.max_duration)
    if (key) form.durationPreset = key
    else { form.durationPreset = 'custom'; form.minDuration = prefs.min_duration; form.maxDuration = prefs.max_duration }
  }
}

export function preferencesFrom(form, count, durations) {
  const out = {}
  for (const k of KEYS) out[k] = form[k]
  out.count = count
  out.min_duration = durations[0]
  out.max_duration = durations[1]
  return out
}

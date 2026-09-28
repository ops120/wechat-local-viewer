/**
 * Which models a selector may show for a given provider / entry point.
 *
 * The rules are capability-based, never name-based:
 *
 *  - text chat: the catalog entry must be a text-capable route and must not be
 *    a dedicated non-text route (image generation, video, rerank);
 *  - multimodal: the text rule plus an explicit declaration of the modality
 *    actually being uploaded — a model that does not declare it fails closed;
 *  - embedding / image / video / rerank: strict endpoint matching.
 *
 * The list handed to a selector is always the *filtered* list. Blocking an
 * incompatible attachment at send time is a second-layer guard, not a
 * substitute for filtering the options.
 */

import type { ModelOption } from './provider'

export const TEXT_ENDPOINT_TYPES = ['openai', 'anthropic', 'gemini', 'openai-response']

export const NON_TEXT_ENDPOINT_TYPES = [
  'image-generation',
  'openai-video',
  'jina-rerank',
  'embeddings',
]

export type FilterCapability = 'chat' | 'embedding' | 'image' | 'video' | 'rerank'

export function isChatCompatible(model: ModelOption): boolean {
  const types = model.supported_endpoint_types ?? []
  if (types.some((t) => NON_TEXT_ENDPOINT_TYPES.includes(t))) return false
  return types.some((t) => TEXT_ENDPOINT_TYPES.includes(t))
}

export function supportsInputModality(model: ModelOption, modality: string): boolean {
  const modalities = model.input_modalities ?? []
  if (modalities.length === 0) return false // fail closed on missing metadata
  return modalities.includes(modality)
}

export function filterModelOptions(
  models: ModelOption[],
  capability: FilterCapability,
  modality?: string | null,
): ModelOption[] {
  if (capability === 'chat') {
    const chatModels = models.filter(isChatCompatible)
    if (!modality || modality === 'text') return chatModels
    return chatModels.filter((m) => supportsInputModality(m, modality))
  }
  if (capability === 'embedding') {
    return models.filter((m) => (m.supported_endpoint_types ?? []).includes('embeddings'))
  }
  if (capability === 'image') {
    return models.filter((m) => (m.supported_endpoint_types ?? []).includes('image-generation'))
  }
  if (capability === 'video') {
    return models.filter((m) => (m.supported_endpoint_types ?? []).includes('openai-video'))
  }
  if (capability === 'rerank') {
    return models.filter((m) => (m.supported_endpoint_types ?? []).includes('jina-rerank'))
  }
  return []
}

/** Whether a previously selected id survives a re-filter. */
export function isModelStillAllowed(
  models: ModelOption[],
  modelId: string,
  capability: FilterCapability,
  modality?: string | null,
): boolean {
  if (!modelId) return false
  return filterModelOptions(models, capability, modality).some((m) => m.id === modelId)
}

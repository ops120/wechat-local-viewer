import { describe, expect, it } from 'vitest'
import {
  filterModelOptions,
  isChatCompatible,
  isModelStillAllowed,
  supportsInputModality,
} from '../modelSelection'
import type { ModelOption } from '../provider'

function model(partial: Partial<ModelOption> & { id: string }): ModelOption {
  return {
    name: '',
    context_length: null,
    max_completion_tokens: null,
    input_modalities: [],
    supported_endpoint_types: [],
    reasoning_efforts: [],
    source: 'live',
    ...partial,
  }
}

const CATALOG: ModelOption[] = [
  model({ id: 'acme/text-only', supported_endpoint_types: ['openai'], input_modalities: ['text'] }),
  model({
    id: 'acme/vision-chat',
    supported_endpoint_types: ['openai', 'anthropic'],
    input_modalities: ['text', 'image'],
  }),
  model({ id: 'acme/audio-chat', supported_endpoint_types: ['gemini'], input_modalities: ['text', 'audio'] }),
  model({ id: 'acme/embed-small', supported_endpoint_types: ['embeddings'], input_modalities: ['text'] }),
  model({ id: 'acme/image-xl', supported_endpoint_types: ['image-generation'], input_modalities: ['text'] }),
  model({ id: 'acme/video-1', supported_endpoint_types: ['openai-video'] }),
  model({ id: 'acme/rerank-1', supported_endpoint_types: ['jina-rerank'] }),
  model({ id: 'acme/undeclared', supported_endpoint_types: ['openai'] }),
]

const ids = (models: ModelOption[]) => models.map((m) => m.id)

describe('chat capability', () => {
  it('keeps text-capable routes', () => {
    expect(ids(filterModelOptions(CATALOG, 'chat'))).toEqual([
      'acme/text-only',
      'acme/vision-chat',
      'acme/audio-chat',
      'acme/undeclared',
    ])
  })

  it('excludes dedicated non-text routes', () => {
    const chat = ids(filterModelOptions(CATALOG, 'chat'))
    for (const excluded of ['acme/embed-small', 'acme/image-xl', 'acme/video-1', 'acme/rerank-1']) {
      expect(chat).not.toContain(excluded)
    }
  })

  it('accepts every text endpoint type', () => {
    for (const type of ['openai', 'anthropic', 'gemini', 'openai-response']) {
      expect(isChatCompatible(model({ id: 'x', supported_endpoint_types: [type] }))).toBe(true)
    }
  })
})

describe('multimodal fail-closed', () => {
  it('offers only models that declare the uploaded modality', () => {
    expect(ids(filterModelOptions(CATALOG, 'chat', 'image'))).toEqual(['acme/vision-chat'])
  })

  it('does not offer a chat model that never declared image input', () => {
    const withImage = ids(filterModelOptions(CATALOG, 'chat', 'image'))
    expect(withImage).not.toContain('acme/text-only')
    // Missing metadata fails closed rather than being assumed compatible.
    expect(withImage).not.toContain('acme/undeclared')
  })

  it('filters audio independently', () => {
    expect(ids(filterModelOptions(CATALOG, 'chat', 'audio'))).toEqual(['acme/audio-chat'])
  })

  it('fails closed for an unsupported modality', () => {
    expect(filterModelOptions(CATALOG, 'chat', 'video')).toEqual([])
    expect(supportsInputModality(model({ id: 'x' }), 'image')).toBe(false)
  })

  it('is unaffected by a text modality', () => {
    expect(ids(filterModelOptions(CATALOG, 'chat', 'text'))).toEqual(
      ids(filterModelOptions(CATALOG, 'chat')),
    )
  })
})

describe('specialised capabilities', () => {
  it('matches strictly per route', () => {
    expect(ids(filterModelOptions(CATALOG, 'embedding'))).toEqual(['acme/embed-small'])
    expect(ids(filterModelOptions(CATALOG, 'image'))).toEqual(['acme/image-xl'])
    expect(ids(filterModelOptions(CATALOG, 'video'))).toEqual(['acme/video-1'])
    expect(ids(filterModelOptions(CATALOG, 'rerank'))).toEqual(['acme/rerank-1'])
  })
})

describe('stale selection invalidation', () => {
  it('detects a model that no longer survives the filter', () => {
    expect(isModelStillAllowed(CATALOG, 'acme/text-only', 'chat')).toBe(true)
    // Adding an image makes the text-only selection invalid.
    expect(isModelStillAllowed(CATALOG, 'acme/text-only', 'chat', 'image')).toBe(false)
    expect(isModelStillAllowed(CATALOG, 'acme/vision-chat', 'chat', 'image')).toBe(true)
    // A chat model is never valid for an embedding entry point.
    expect(isModelStillAllowed(CATALOG, 'acme/text-only', 'embedding')).toBe(false)
    expect(isModelStillAllowed(CATALOG, '', 'chat')).toBe(false)
  })
})

describe('reasoning metadata survives filtering', () => {
  it('keeps the verified effort ladder on the option handed to the selector', () => {
    const gpt = model({
      id: 'openai/gpt-5.5',
      supported_endpoint_types: ['openai'],
      input_modalities: ['text', 'image'],
      reasoning_efforts: ['low', 'medium', 'high', 'xhigh'],
      source: 'verified-seed',
    })
    const [option] = filterModelOptions([gpt], 'chat')
    expect(option.reasoning_efforts).toEqual(['low', 'medium', 'high', 'xhigh'])
    expect(option.source).toBe('verified-seed')
  })
})

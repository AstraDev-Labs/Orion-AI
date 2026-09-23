import type { ModelInfo } from '../types';

export const MODEL_PREFERENCE_KEY = 'orion-chat-model';

export function isChatModel(model: ModelInfo): boolean {
  if (model.purpose) return model.purpose === 'chat';
  // Compatibility with older servers that do not publish model roles yet.
  const family = model.id.toLowerCase().split('/').pop()!.split(':')[0];
  return !/^(moondream(?:-|$)|nomic-embed|mxbai-embed|snowflake-arctic-embed|bge-|embeddinggemma)/.test(family);
}

export function savedChatModel(): string {
  try { return localStorage.getItem(MODEL_PREFERENCE_KEY) || ''; } catch { return ''; }
}

export function chooseChatModel(models: ModelInfo[], preferred: string, saved = ''): string {
  const chat = models.filter(isChatModel);
  const match = (id: string) => chat.find((m) => m.id.replace(/:latest$/, '') === id.replace(/:latest$/, ''))?.id;
  return (saved && match(saved)) || (preferred && match(preferred)) || chat[0]?.id || '';
}

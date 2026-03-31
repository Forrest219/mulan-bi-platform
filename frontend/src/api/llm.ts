const API_BASE = '/api';

export interface LLMConfig {
  id: number;
  provider: string;
  base_url: string;
  model: string;
  temperature: number;
  max_tokens: number;
  is_active: boolean;
  has_api_key: boolean;
  created_at: string;
  updated_at: string;
}

export interface LLMConfigInput {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
  max_tokens: number;
  is_active: boolean;
}

export interface LLMTestResult {
  success: boolean;
  message: string;
}

export interface AssetSummaryResult {
  summary: string | null;
  error?: string;
  cached: boolean;
}

export async function getLLMConfig(): Promise<{ config: LLMConfig | null; message?: string }> {
  const res = await fetch(`${API_BASE}/llm/config`, { credentials: 'include' });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '获取 LLM 配置失败');
  }
  return res.json();
}

export async function saveLLMConfig(data: LLMConfigInput): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/llm/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '保存失败');
  }
  return res.json();
}

export async function testLLMConnection(prompt?: string): Promise<LLMTestResult> {
  const res = await fetch(`${API_BASE}/llm/config/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ prompt: prompt || "Hello, respond with 'OK'" }),
  });
  return res.json();
}

export async function deleteLLMConfig(): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/llm/config`, { method: 'DELETE', credentials: 'include' });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '删除失败');
  }
  return res.json();
}

export async function getAssetSummary(assetId: number, refresh = false): Promise<AssetSummaryResult> {
  const params = new URLSearchParams({ refresh: String(refresh) });
  const res = await fetch(`${API_BASE}/llm/assets/${assetId}/summary?${params}`, { credentials: 'include' });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '获取摘要失败');
  }
  return res.json();
}

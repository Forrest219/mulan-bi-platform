import { useState, useEffect } from 'react';
import {
  getAsset,
  getAssetChildren,
  getAssetParent,
  getAssetFields,
  getDatasourceMetadata,
  explainAsset,
  getAssetHealth,
  TableauAsset,
  AssetHealth,
} from '../../../api/tableau';
import { getAssetSummary, getLLMConfig } from '../../../api/llm';
import type { FieldMetadataStatus, FieldSemantic } from '../types';

type ActiveTab = 'info' | 'datasources' | 'ai' | 'children' | 'fields' | 'health' | 'impact';

interface ConfirmModalState {
  open: boolean;
  title: string;
  message: string;
  onConfirm: () => void;
}

function getHealthLevel(score: number): AssetHealth['level'] {
  if (score >= 80) return 'excellent';
  if (score >= 60) return 'good';
  if (score >= 40) return 'warning';
  return 'poor';
}

function normalizeHealthDetails(asset: TableauAsset): AssetHealth | null {
  if (asset.health_details && typeof asset.health_details.score === 'number') {
    return {
      score: asset.health_details.score,
      level: asset.health_details.level || getHealthLevel(asset.health_details.score),
      checks: Array.isArray(asset.health_details.checks) ? asset.health_details.checks : [],
    };
  }
  if (asset.health_score != null) {
    return {
      score: asset.health_score,
      level: getHealthLevel(asset.health_score),
      checks: [],
    };
  }
  return null;
}

export interface UseAssetDetailResult {
  asset: TableauAsset | null;
  loading: boolean;
  error: string | null;

  children: TableauAsset[];
  childrenLoading: boolean;

  parent: TableauAsset | null;

  aiContent: string | null;
  aiLoading: boolean;
  aiError: string | null;
  aiCached: boolean;
  llmConfigured: boolean;
  handleRefreshAI: () => void;

  healthData: AssetHealth | null;
  healthLoading: boolean;
  healthError: string | null;
  loadHealth: () => void;

  fieldSemantics: FieldSemantic[];
  fieldMetadata: FieldMetadataStatus | null;
  fieldsLoading: boolean;

  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;

  confirmModal: ConfirmModalState | null;
  setConfirmModal: (modal: ConfirmModalState | null) => void;

  loadAIExplain: (refresh?: boolean) => void;
}

export function useAssetDetail(id: string | undefined, defaultTab?: string): UseAssetDetailResult {
  const [asset, setAsset] = useState<TableauAsset | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>((defaultTab as ActiveTab) || 'info');

  // AI state
  const [aiExplain, setAiExplain] = useState<string | null>(null);
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiCached, setAiCached] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState(true);
  const [fieldSemantics, setFieldSemantics] = useState<FieldSemantic[]>([]);
  const [fieldMetadata, setFieldMetadata] = useState<FieldMetadataStatus | null>(null);
  const [fieldsLoading, setFieldsLoading] = useState(false);

  // Health state
  const [healthData, setHealthData] = useState<AssetHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  // Hierarchy state
  const [parent, setParent] = useState<TableauAsset | null>(null);
  const [children, setChildren] = useState<TableauAsset[]>([]);
  const [childrenLoading, setChildrenLoading] = useState(false);

  const [confirmModal, setConfirmModal] = useState<ConfirmModalState | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);
    setParent(null);
    setChildren([]);
    setAiExplain(null);
    setAiSummary(null);
    setAiError(null);
    setHealthData(null);
    setHealthError(null);
    setFieldSemantics([]);
    setFieldMetadata(null);

    getAsset(Number(id))
      .then(a => {
        setAsset(a);
        setHealthData(normalizeHealthDetails(a));
        // Load parent for views/dashboards
        if (a.asset_type === 'view' || a.asset_type === 'dashboard') {
          getAssetParent(a.id).then(d => setParent(d.parent)).catch(() => {});
        }
        // Load children for workbooks
        if (a.asset_type === 'workbook') {
          setChildrenLoading(true);
          getAssetChildren(a.id)
            .then(d => setChildren(d.children))
            .catch(() => {})
            .finally(() => setChildrenLoading(false));
        }
        // 独立加载字段元数据
        setFieldsLoading(true);
        const fieldsRequest = a.asset_type === 'datasource'
          ? getDatasourceMetadata(a.id).catch(() => getAssetFields(a.id))
          : getAssetFields(a.id);
        fieldsRequest
          .then(d => {
            setFieldSemantics(d.fields);
            setFieldMetadata({
              field_count: d.field_count,
              local_field_count: d.local_field_count,
              cache_status: d.cache_status,
              cached_at: d.cached_at,
              updated_at: d.updated_at,
            });
          })
          .catch(() => {})
          .finally(() => setFieldsLoading(false));
      })
      .catch(() => setError('资产加载失败'))
      .finally(() => setLoading(false));

    getLLMConfig().then(d => {
      setLlmConfigured(!!d.config && d.config.is_active);
    }).catch(() => setLlmConfigured(false));
  }, [id]);

  // Load deep AI explain (Phase 2a)
  async function loadAIExplain(refresh = false) {
    if (!id) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const result = await explainAsset(Number(id), refresh);
      setAiExplain(result.explain);
      setAiCached(result.cached);
      setAiError(result.error || null);
      if (result.field_semantics) {
        setFieldSemantics(result.field_semantics);
        setFieldMetadata(prev => prev || { field_count: result.field_semantics?.length });
      }
    } catch {
      // Fallback to basic summary if explain fails
      try {
        const result = await getAssetSummary(Number(id), refresh);
        setAiSummary(result.summary);
        setAiCached(result.cached);
        setAiError(result.error || null);
      } catch (e: any) {
        setAiError(e.message || '获取解读失败');
      }
    } finally {
      setAiLoading(false);
    }
  }

  function handleRefreshAI() {
    const aiContent = aiExplain || aiSummary;
    if (aiContent) {
      setConfirmModal({
        open: true,
        title: '重新生成解读',
        message: '确定要重新生成 AI 深度解读吗？之前的解读将被覆盖。',
        onConfirm: () => { setConfirmModal(null); loadAIExplain(true); },
      });
    } else {
      loadAIExplain(false);
    }
  }

  // Load health data
  async function loadHealth() {
    if (!id) return;
    setHealthLoading(true);
    setHealthError(null);
    try {
      const data = await getAssetHealth(Number(id));
      setHealthData(data);
    } catch (_err) {
      // ignore health load failures on detail page
    }
    setHealthLoading(false);
  }

  const aiContent = aiExplain || aiSummary;

  return {
    asset,
    loading,
    error,
    children,
    childrenLoading,
    parent,
    aiContent,
    aiLoading,
    aiError,
    aiCached,
    llmConfigured,
    handleRefreshAI,
    healthData,
    healthLoading,
    healthError,
    loadHealth,
    fieldSemantics,
    fieldMetadata,
    fieldsLoading,
    activeTab,
    setActiveTab,
    confirmModal,
    setConfirmModal,
    loadAIExplain,
  };
}

import { useState } from 'react';
import type { FieldSemantic } from '../types';
import { explainAsset } from '../../../api/tableau';

export function useAssetFields(assetId: string | undefined) {
  const [fieldSemantics, setFieldSemantics] = useState<FieldSemantic[]>([]);
  const [fieldsLoading, setFieldsLoading] = useState(false);
  const [fieldsError, setFieldsError] = useState<string | null>(null);

  async function loadFields() {
    if (!assetId) return;
    setFieldsLoading(true);
    setFieldsError(null);
    try {
      const result = await explainAsset(Number(assetId), false);
      if (result.field_semantics) {
        setFieldSemantics(result.field_semantics);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '字段加载失败';
      setFieldsError(msg);
    } finally {
      setFieldsLoading(false);
    }
  }

  return { fieldSemantics, fieldsLoading, fieldsError, loadFields };
}

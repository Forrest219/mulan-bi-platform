import { useState } from 'react';
import { getAssetHealth, type AssetHealth } from '../../../api/tableau';

export function useAssetHealth(assetId: string | undefined) {
  const [healthData, setHealthData] = useState<AssetHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  async function loadHealth() {
    if (!assetId) return;
    setHealthLoading(true);
    setHealthError(null);
    try {
      const data = await getAssetHealth(Number(assetId));
      setHealthData(data);
    } catch {
      setHealthError('健康度加载失败');
    } finally {
      setHealthLoading(false);
    }
  }

  return { healthData, healthLoading, healthError, loadHealth };
}

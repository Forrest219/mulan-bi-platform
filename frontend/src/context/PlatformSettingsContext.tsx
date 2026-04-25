import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { API_BASE, LOGO_URL as FALLBACK_LOGO_URL } from '../config';

export interface PlatformSettings {
  id: number;
  platform_name: string;
  platform_subtitle: string | null;
  logo_url: string;
  favicon_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformSettingsContextType {
  settings: PlatformSettings;
  isLoading: boolean;
  updateSettings: (newSettings: Partial<PlatformSettings>) => Promise<void>;
  /** 仅更新本地状态（不调 API），用于表单输入时实时预览 */
  previewSettings: (patch: Partial<PlatformSettings>) => void;
}

const DEFAULT_SETTINGS: PlatformSettings = {
  id: 1,
  platform_name: '木兰 BI 平台',
  platform_subtitle: '数据建模与治理平台',
  logo_url: FALLBACK_LOGO_URL,
  favicon_url: null,
  created_at: '',
  updated_at: '',
};

const PlatformSettingsContext = createContext<PlatformSettingsContextType | undefined>(undefined);

export function PlatformSettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<PlatformSettings>(DEFAULT_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const loadSettings = async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/platform-settings/`, {
          credentials: 'include',
        });
        if (resp.ok) {
          const data: PlatformSettings = await resp.json();
          setSettings(data);
        }
        // resp.ok=false 时静默使用默认配置，不阻塞 UI
      } catch (_err) {
        // 网络错误时使用默认配置
      } finally {
        setIsLoading(false);
      }
    };
    loadSettings();
  }, []);

  const updateSettings = async (newSettings: Partial<PlatformSettings>) => {
    console.log('[PlatformSettingsContext] PUT /api/platform-settings/', newSettings);
    const resp = await fetch(`${API_BASE}/api/platform-settings/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(newSettings),
    });
    console.log('[PlatformSettingsContext] PUT response:', resp.status, resp.statusText);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: '更新失败' }));
      console.error('[PlatformSettingsContext] PUT error:', err);
      throw new Error(err.detail || '更新平台设置失败');
    }
    const updated: PlatformSettings = await resp.json();
    console.log('[PlatformSettingsContext] PUT success:', updated);
    setSettings(updated);
  };

  /** 仅更新本地状态（不调 API），用于表单输入时实时预览侧边栏 */
  const previewSettings = (patch: Partial<PlatformSettings>) => {
    setSettings(prev => ({ ...prev, ...patch }));
  };

  return (
    <PlatformSettingsContext.Provider value={{ settings, isLoading, updateSettings, previewSettings }}>
      {children}
    </PlatformSettingsContext.Provider>
  );
}

export function usePlatformSettings() {
  const ctx = useContext(PlatformSettingsContext);
  if (!ctx) {
    // 降级：返回默认配置（理论上 AppShellLayout 外不会用到）
    return { settings: DEFAULT_SETTINGS, isLoading: false, updateSettings: async () => {}, previewSettings: () => {} };
  }
  return ctx;
}

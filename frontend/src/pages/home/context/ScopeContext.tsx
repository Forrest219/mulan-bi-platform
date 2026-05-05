/**
 * ScopeContext — 重新导出自 features/ops-workbench/ScopeContext
 *
 * 保留此文件是为了向后兼容，确保所有 pages/home/ 下的组件
 * 可以从 './context/ScopeContext' 导入 useScope。
 */
export { ScopeProvider, useScope, ScopeContext } from '../../../features/ops-workbench/ScopeContext';

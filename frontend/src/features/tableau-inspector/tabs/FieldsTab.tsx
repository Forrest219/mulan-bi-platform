import { FieldSemantic } from '../types';

interface FieldsTabProps {
  fieldSemantics: FieldSemantic[];
  aiLoading: boolean;
}

export function FieldsTab({ fieldSemantics, aiLoading }: FieldsTabProps) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-100">
        <h3 className="text-sm font-semibold text-slate-700">字段元数据</h3>
        <p className="text-xs text-slate-400 mt-0.5">数据源字段信息（需先生成 AI 解读以加载字段）</p>
      </div>
      {fieldSemantics.length === 0 ? (
        <div className="text-center py-10 text-slate-400 text-xs">
          {aiLoading ? '正在加载字段数据...' : '暂无字段数据，请先在 AI 解读 Tab 生成解读'}
        </div>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="bg-slate-50">
              {['字段名', '中文名', '数据类型', '角色', '描述'].map(h => (
                <th key={h} className="text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wide px-4 py-2.5">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fieldSemantics.map((f, i) => (
              <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-2.5 text-xs font-mono text-slate-700">{f.field}</td>
                <td className="px-4 py-2.5 text-xs text-slate-600">{f.caption || '-'}</td>
                <td className="px-4 py-2.5 text-xs text-slate-500">{f.data_type || '-'}</td>
                <td className="px-4 py-2.5">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                    f.role === 'measure' ? 'bg-blue-50 text-blue-600' : 'bg-slate-100 text-slate-600'
                  }`}>{f.role || '-'}</span>
                </td>
                <td className="px-4 py-2.5 text-xs text-slate-500 max-w-xs truncate">{f.meaning || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

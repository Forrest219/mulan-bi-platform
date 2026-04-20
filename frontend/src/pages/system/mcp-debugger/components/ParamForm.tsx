import React, { useEffect, useState } from 'react';
import type { McpTool } from '../../../../api/mcpDebug';

interface Props {
  tool: McpTool;
  initialValues?: Record<string, unknown>;
  onSubmit: (args: Record<string, unknown>) => void;
  loading: boolean;
}

type FieldValue = string | number | boolean;

export default function ParamForm({ tool, initialValues, onSubmit, loading }: Props) {
  const [values, setValues] = useState<Record<string, FieldValue>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const schema = tool.inputSchema;
  const properties = schema?.properties ?? {};
  const required = schema?.required ?? [];

  // 当 tool 或 initialValues 变化时重置表单
  useEffect(() => {
    const init: Record<string, FieldValue> = {};
    for (const [key, prop] of Object.entries(properties)) {
      if (initialValues && key in initialValues) {
        const v = initialValues[key];
        if (prop.type === 'boolean') {
          init[key] = Boolean(v);
        } else if (prop.type === 'integer' || prop.type === 'number') {
          init[key] = v as number;
        } else if (prop.type === 'array' || prop.type === 'object') {
          init[key] = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
        } else {
          init[key] = String(v ?? '');
        }
      } else {
        if (prop.type === 'boolean') init[key] = false;
        else if (prop.type === 'array' || prop.type === 'object') init[key] = '';
        else init[key] = '';
      }
    }
    setValues(init);
    setErrors({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool.name, tool.inputSchema, initialValues]);

  const handleChange = (key: string, value: FieldValue) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    if (errors[key]) setErrors((prev) => ({ ...prev, [key]: '' }));
  };

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};
    for (const key of required) {
      const v = values[key];
      if (v === undefined || v === '' || v === null) {
        newErrors[key] = '此字段为必填项';
      }
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    const args: Record<string, unknown> = {};
    for (const [key, prop] of Object.entries(properties)) {
      const v = values[key];
      if (v === undefined || v === '') continue;

      if (prop.type === 'integer') {
        args[key] = parseInt(String(v), 10);
      } else if (prop.type === 'number') {
        args[key] = parseFloat(String(v));
      } else if (prop.type === 'boolean') {
        args[key] = Boolean(v);
      } else if (prop.type === 'array' || prop.type === 'object') {
        try {
          args[key] = JSON.parse(String(v));
        } catch {
          setErrors((prev) => ({ ...prev, [key]: 'JSON 格式错误' }));
          return;
        }
      } else {
        args[key] = v;
      }
    }
    onSubmit(args);
  };

  const fieldEntries = Object.entries(properties);

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      {fieldEntries.length === 0 && (
        <div className="text-sm text-slate-400 italic">此工具无需参数</div>
      )}

      {fieldEntries.map(([key, prop]) => {
        const isRequired = required.includes(key);
        const label = (
          <label className="block text-sm font-medium text-slate-700 mb-1">
            {key}
            {isRequired && <span className="text-red-500 ml-1">*</span>}
            {prop.description && (
              <span className="ml-2 text-xs font-normal text-slate-400">
                {prop.description}
              </span>
            )}
          </label>
        );

        let input: React.ReactNode;

        if (prop.type === 'boolean') {
          input = (
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id={`field-${key}`}
                checked={Boolean(values[key])}
                onChange={(e) => handleChange(key, e.target.checked)}
                className="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500"
              />
              <label htmlFor={`field-${key}`} className="text-sm text-slate-600">
                {values[key] ? '是' : '否'}
              </label>
            </div>
          );
        } else if (prop.type === 'array' || prop.type === 'object') {
          input = (
            <textarea
              value={String(values[key] ?? '')}
              onChange={(e) => handleChange(key, e.target.value)}
              rows={4}
              placeholder={`JSON ${prop.type === 'array' ? '数组' : '对象'}`}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono resize-y"
            />
          );
        } else if (prop.type === 'integer' || prop.type === 'number') {
          input = (
            <input
              type="number"
              value={String(values[key] ?? '')}
              onChange={(e) => handleChange(key, e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          );
        } else if (prop.enum) {
          input = (
            <select
              value={String(values[key] ?? '')}
              onChange={(e) => handleChange(key, e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">-- 请选择 --</option>
              {prop.enum.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          );
        } else {
          input = (
            <input
              type="text"
              value={String(values[key] ?? '')}
              onChange={(e) => handleChange(key, e.target.value)}
              className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          );
        }

        return (
          <div key={key}>
            {label}
            {input}
            {errors[key] && (
              <p className="mt-1 text-xs text-red-500">{errors[key]}</p>
            )}
          </div>
        );
      })}

      <button
        type="submit"
        disabled={loading}
        className="mt-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
      >
        {loading ? (
          <>
            <i className="ri-loader-4-line animate-spin" />
            执行中...
          </>
        ) : (
          <>
            <i className="ri-play-line" />
            执行
          </>
        )}
      </button>
    </form>
  );
}

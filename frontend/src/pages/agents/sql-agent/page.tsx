import { useState } from 'react';
import { useParams } from 'react-router-dom';

export default function SqlAgentPage() {
  const params = useParams();
  const [loading, setLoading] = useState(false);

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">SQL Agent</h1>
        <p className="text-gray-500 mt-1">自然语言转 SQL 查询与 SQL 优化</p>
      </div>

      {/* 页面内容占位 */}
      <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-400">
        功能开发中，敬请期待
      </div>
    </div>
  );
}

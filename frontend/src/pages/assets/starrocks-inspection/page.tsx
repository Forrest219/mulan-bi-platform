import { useState } from 'react';
import { useParams } from 'react-router-dom';

export default function StarRocksInspectionPage() {
  const params = useParams();
  const [loading, setLoading] = useState(false);

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">StarRocks 巡检</h1>
        <p className="text-gray-500 mt-1">StarRocks 数据库健康检查与巡检报告</p>
      </div>

      {/* 页面内容占位 */}
      <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-400">
        功能开发中，敬请期待
      </div>
    </div>
  );
}

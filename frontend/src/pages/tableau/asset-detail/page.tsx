import { useParams, Link } from 'react-router-dom';
import { AssetInspector } from '../../../features/tableau-inspector/AssetInspector';

export default function AssetDetailPage() {
  const { id } = useParams<{ id: string }>();
  if (!id) return null;
  return (
    <>
      <div className="bg-blue-50 border-b border-blue-200 px-4 py-2 flex items-center justify-between text-sm text-blue-700">
        <span>提示：可在运维工作台一屏查看资产与问数</span>
        <Link to={`/?asset=${id}&tab=info`} className="font-medium underline hover:text-blue-900">
          在工作台打开 →
        </Link>
      </div>
      <AssetInspector assetId={id} layout="page" />
    </>
  );
}

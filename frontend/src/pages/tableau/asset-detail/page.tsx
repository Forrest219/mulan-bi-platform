import { useParams } from 'react-router-dom';
import { AssetInspector } from '../../../features/tableau-inspector/AssetInspector';

export default function AssetDetailPage() {
  const { id } = useParams<{ id: string }>();
  if (!id) return null;
  return <AssetInspector assetId={id} layout="page" />;
}

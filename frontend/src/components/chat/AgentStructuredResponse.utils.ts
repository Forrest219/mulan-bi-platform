export type JsonRecord = Record<string, unknown>;

export interface NormalizedStructuredResponse {
  responseType?: string | null;
  payload?: JsonRecord;
}

export interface StructuredFieldGroup {
  name?: string;
  fields: JsonRecord[];
}

export interface StructuredAnalysisSuggestion {
  title: string;
  fields: string[];
  exampleQuestions: string[];
}

export function asRecord(value: unknown): JsonRecord | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  return value as JsonRecord;
}

export function normalizeStructuredResponse(
  responseType?: string | null,
  responseData?: unknown,
): NormalizedStructuredResponse {
  const envelope = asRecord(responseData);
  if (envelope && typeof envelope.response_type === 'string' && asRecord(envelope.response_data)) {
    return {
      responseType: envelope.response_type,
      payload: asRecord(envelope.response_data),
    };
  }
  return {
    responseType,
    payload: asRecord(responseData),
  };
}

export function shouldRenderStructuredResponse(responseType?: string | null, responseData?: unknown): boolean {
  const normalized = normalizeStructuredResponse(responseType, responseData);
  const type = normalized.responseType;
  if (!type || !normalized.payload) return false;
  return [
    'asset_candidates',
    'asset_metadata',
    'asset_not_found',
    'tool_unavailable',
    'clarification',
    'query_result',
    'table',
  ].includes(type);
}

export function shouldSuppressAnswerMarkdown(responseType?: string | null, responseData?: unknown): boolean {
  const normalized = normalizeStructuredResponse(responseType, responseData);
  return [
    'asset_candidates',
    'asset_metadata',
    'asset_not_found',
    'tool_unavailable',
    'clarification',
  ].includes(normalized.responseType ?? '');
}

function textValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  return String(value);
}

export function normalizeStructuredFields(value: unknown): JsonRecord[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const record = asRecord(item);
    return record ?? { name: textValue(item) };
  });
}

export function normalizeFieldGroups(value: unknown): StructuredFieldGroup[] {
  if (Array.isArray(value)) {
    return value
      .map((item): StructuredFieldGroup | undefined => {
        const record = asRecord(item);
        if (!record) return undefined;
        const fields = normalizeStructuredFields(record.fields);
        if (fields.length === 0) return undefined;
        return {
          name: textValue(record.label)
            || textValue(record.title)
            || textValue(record.name)
            || textValue(record.table_name)
            || textValue(record.logical_table_name)
            || undefined,
          fields,
        };
      })
      .filter((item): item is StructuredFieldGroup => !!item);
  }

  const record = asRecord(value);
  if (!record) return [];
  return Object.entries(record)
    .map(([name, fields]): StructuredFieldGroup | undefined => {
      const normalizedFields = normalizeStructuredFields(fields);
      if (normalizedFields.length === 0) return undefined;
      return { name, fields: normalizedFields };
    })
    .filter((item): item is StructuredFieldGroup => !!item);
}

export function fieldGroupsFromAssetMetadata(payload: JsonRecord): StructuredFieldGroup[] {
  const groupedFields = normalizeFieldGroups(payload.field_groups ?? payload.fieldGroups);
  if (groupedFields.length > 0) return groupedFields;

  const fields = normalizeStructuredFields(payload.fields);
  return fields.length > 0 ? [{ fields }] : [];
}

export function normalizeAnalysisSuggestions(value: unknown): StructuredAnalysisSuggestion[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const record = asRecord(item);
      if (!record) return undefined;
      const title = textValue(record.title);
      const fields = Array.isArray(record.fields)
        ? record.fields.map(textValue).filter(Boolean)
        : [];
      const exampleQuestions = [
        ...(Array.isArray(record.example_questions) ? record.example_questions.map(textValue) : []),
        ...(Array.isArray(record.exampleQuestions) ? record.exampleQuestions.map(textValue) : []),
        ...(textValue(record.question) ? [textValue(record.question)] : []),
      ].filter(Boolean);
      if (!title && fields.length === 0 && exampleQuestions.length === 0) return undefined;
      return {
        title: title || '分析建议',
        fields,
        exampleQuestions,
      };
    })
    .filter((item): item is StructuredAnalysisSuggestion => !!item);
}

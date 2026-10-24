import { api } from './client'
import type { CatalogResponse, Exposure } from '@/types/catalog'

export interface CatalogQuery {
  exposure?: Exposure
  stage?: string
  backend?: string
}

export const getCatalog = (query: CatalogQuery = {}): Promise<CatalogResponse> =>
  api.get<CatalogResponse>('/catalog', { params: query })

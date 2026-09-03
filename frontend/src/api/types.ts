// Types mirroring the backend's Pydantic response schemas
// (backend/app/schemas/*.py) — kept hand-in-sync rather than generated,
// same as every other part of this project (no OpenAPI codegen step).

export type UserRole =
  | 'platform_admin'
  | 'restaurant_owner'
  | 'restaurant_manager'
  | 'restaurant_staff'

export interface User {
  id: string
  email: string
  first_name: string | null
  last_name: string | null
  role: UserRole
  restaurant_id: string | null
  is_active: boolean
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface Restaurant {
  id: string
  name: string
  description: string | null
  address: string | null
  city: string | null
  state: string | null
  postal_code: string | null
  country: string | null
  phone_number: string | null
  website: string | null
  email: string | null
  timezone: string
  transfer_number: string | null
  menu_url: string | null
  ai_greeting: string | null
  stt_vocabulary: string | null
  // null means "use the deployment-wide default" — see Restaurant in
  // backend/app/db/models.py.
  takes_reservations: boolean | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type RestaurantUpdatePayload = Partial<
  Omit<Restaurant, 'id' | 'is_active' | 'created_at' | 'updated_at'>
>

export interface HoursEntry {
  day_of_week: number // 0=Monday .. 6=Sunday
  opening_time: string // HH:MM
  closing_time: string // HH:MM
  is_closed: boolean
}

export interface HoursRead extends HoursEntry {
  id: string
}

export interface FAQ {
  id: string
  restaurant_id: string
  question: string
  answer: string
  category: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type FAQCreatePayload = Pick<FAQ, 'question' | 'answer'> &
  Partial<Pick<FAQ, 'category' | 'is_active'>>
export type FAQUpdatePayload = Partial<Pick<FAQ, 'question' | 'answer' | 'category' | 'is_active'>>

export interface KnowledgeDocument {
  id: string
  restaurant_id: string
  title: string
  content: string
  document_type: string
  source: string | null
  is_active: boolean
  chunk_count: number
  created_at: string
  updated_at: string
}

export type CallOutcome =
  | 'faq_answered'
  | 'reservation_created'
  | 'call_transferred'
  | 'human_escalation'
  | 'call_abandoned'
  | 'unknown'

export interface Call {
  id: string
  restaurant_id: string
  call_sid: string
  caller_number: string
  called_number: string
  start_time: string
  end_time: string | null
  duration_seconds: number | null
  outcome: CallOutcome
  was_transferred: boolean
  was_escalated: boolean
  recording_path: string | null
}

export interface CallTranscriptTurn {
  role: string
  message: string
  timestamp: string
  confidence: number | null
}

export interface CallDetail extends Call {
  transcript: string | null
  transcripts: CallTranscriptTurn[]
}

export type ReservationStatus = 'pending' | 'confirmed' | 'declined' | 'cancelled' | 'completed' | 'no_show'

export interface Reservation {
  id: string
  restaurant_id: string
  customer_name: string
  customer_phone: string
  customer_email: string | null
  reservation_date: string
  reservation_time: string
  party_size: number
  special_notes: string | null
  status: ReservationStatus
  call_sid: string | null
  created_at: string
  updated_at: string
}

export interface ApiError {
  detail: string | { msg: string; loc: (string | number)[] }[]
}

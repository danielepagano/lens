import { writable } from 'svelte/store'
import type { TransactionState } from '../services/api'

export const currentAddress = writable<string | null>(null)
export const nodeContent = writable<string>('')
export const transactionState = writable<TransactionState | null>(null)

import { derived } from 'svelte/store'
import { urlHash } from './urlHash'
import { parseAppHash } from '../utils/appHash'

export const parsedHash = derived(urlHash, (h) => parseAppHash(h))

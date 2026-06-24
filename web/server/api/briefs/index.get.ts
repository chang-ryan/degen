import { listDates } from '../../utils/db'

export default defineEventHandler(async () => {
  return { dates: await listDates() }
})

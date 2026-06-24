import { getBrief, getLatestBrief } from '../../utils/db'

export default defineEventHandler(async (event) => {
  const date = getRouterParam(event, 'date')
  const brief = !date || date === 'latest' ? await getLatestBrief() : await getBrief(date)
  if (!brief) {
    throw createError({ statusCode: 404, statusMessage: `No brief for ${date}` })
  }
  return brief
})

/** True when both ends of a date window are set and the start is after the end (the API refuses it with a 422). */
export function isInverted(from: string, to: string): boolean {
  return from !== '' && to !== '' && from > to
}

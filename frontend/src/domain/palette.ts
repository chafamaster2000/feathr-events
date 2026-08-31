// One colour per event type, for every chart that splits by type.
//
// Shared so a type keeps its colour across views: `conversion` purple in the history
// chart and green in the live one would make the two charts unreadable together.
//
// Anchored on the client's navy and cyan, extended with hues that stay distinguishable on
// white. Semantic colours are deliberately not reused — green here does not mean "good",
// it means "signup".
export const SERIES = ['#19263c', '#0d9bb4', '#7b5cd6', '#c47f0a', '#0b7a52', '#c02434']

/**
 * Colour by position in the sorted list of types, never by rank or by volume: a type that
 * changes colour when a quiet minute reorders the legend repaints the whole chart for no
 * reason. Callers pass an alphabetically sorted list, which is what the API returns.
 */
export function colorFor(index: number): string {
  return SERIES[index % SERIES.length]
}

import type { Poi } from "../api";

/** One emoji per kind of place: the subcategory first (coffee ≠ fast food), then the category. */
const BY_SUBCATEGORY: Record<string, string> = {
  cafe: "🫖",
  fast_food: "🍔",
  coffee_shop: "☕",
  coffee_vending: "☕",
  restaurant: "🍽️",
  bakery: "🥐",
  confectionery: "🍩",
  cafe_confectionery: "🍩",
  canteen: "🍜",
  pizzeria: "🍕",
  cooking_shop: "🥡",
  sushi: "🍣",
  ice_cream: "🍦",
  food_court: "🍕",
  bar: "🍹",
  pub: "🍻",
  karaoke: "🎶",
  nightclub: "🪩",
  sports_pitch: "⚽",
  track: "🏃",
  sports_centre: "💪",
  fitness_centre: "💪",
  fitness_station: "💪",
  swimming_pool: "🛟",
  stadium: "🏆",
  sports_hall: "🏀",
  golf_course: "⛳",
  bowling_alley: "🎳",
  billiards: "🎱",
  playground: "🎠",
  indoor_play: "🪅",
  mall: "🛍️",
  hotel: "🏨",
  hostel: "🛏️",
  apartment: "🏢",
  guest_house: "🏡",
  motel: "🛏️",
  chalet: "🏡",
  caravan_site: "🏕️",
  tourist_information: "💡",
  toilets: "🚻",
  park: "🌲",
  garden: "🌷",
  common: "🌿",
  picnic_site: "🧺",
  viewpoint: "🌇",
  monument: "🗿",
  memorial: "🕯️",
  artwork: "🎨",
  place_of_worship: "🕌",
  spirituality: "🕌",
  attraction: "📸",
  locations: "📌",
  museum: "🏛️",
  gallery: "🖼️",
  theatre: "🎭",
  arts_centre: "🎭",
  community_centre: "🏛️",
  cinema: "🎬",
  amusement_ride: "🎡",
  amusement_arcade: "🕹️",
  virtual_reality: "🚀",
  aquarium: "🫧",
  dance: "🩰",
  bandstand: "🎶",
  leisure: "🎯",
  library: "📚",
  coworking: "💻",
  sauna: "🥵",
  spa: "😌",
};

const BY_CATEGORY: Record<string, string> = {
  food_drink: "🍽️",
  nature: "🌲",
  culture: "🏛️",
  sightseeing: "📸",
  children: "🎈",
  entertainment: "🎡",
  quiet_spaces: "📚",
  sport: "🏆",
  shopping: "🛍️",
  nightlife: "🍹",
  accommodation: "🏨",
  wellness: "😌",
  infrastructure: "💡",
  other: "📍",
};

export function placeEmoji(p: Pick<Poi, "category"> & { subcategory?: string }): string {
  return (p.subcategory && BY_SUBCATEGORY[p.subcategory]) || BY_CATEGORY[p.category] || "📍";
}

export function categoryEmoji(code: string): string {
  return BY_CATEGORY[code] || "📍";
}

/** Category colors on the dark map: each readable on #14161B and distinct from its neighbours. */
export const CATEGORY_COLORS: Record<string, string> = {
  food_drink: "#F59E5B",
  nature: "#4ADE80",
  culture: "#A78BFA",
  sightseeing: "#00B8D9",
  children: "#F472B6",
  entertainment: "#FB7185",
  quiet_spaces: "#93C5FD",
  sport: "#34D399",
  shopping: "#8B98B0",
  nightlife: "#818CF8",
  accommodation: "#94A3B8",
  wellness: "#5EEAD4",
  infrastructure: "#9AA3B2",
  other: "#9AA3B2",
};

export function categoryColor(code: string): string {
  return CATEGORY_COLORS[code] || "#9AA3B2";
}

/** Landmarks of the start picker, with their own emoji. */
export const LANDMARK_EMOJI: Record<string, string> = {
  bayterek: "🗼",
  mega: "🛍️",
  airport: "✈️",
  museum: "🏛️",
  opera: "🎭",
  ailand: "🎢",
  alem: "🔮",
  expo: "🔮",
};

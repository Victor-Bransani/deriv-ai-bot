/** Casas decimais extra para cotações tipo índice (ex.: 33286.0042). */
export const PRICE_DECIMALS = 4;

export function formatPrice(n: number): string {
  return n.toFixed(PRICE_DECIMALS);
}

/** Formato Lightweight Charts para eixo de preço principal. */
export const chartMainPriceFormat = {
  type: "price" as const,
  precision: PRICE_DECIMALS,
  minMove: 0.0001,
};

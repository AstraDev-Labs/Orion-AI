/**
 * Geometry constants for the Core lattice, shared between the renderer and the
 * HUD chrome that describes it.
 *
 * These live here rather than in holo-stage.js so TypeScript callers get real
 * types: holo-stage.js is plain JS with no declaration file, so importing from
 * it directly resolves to `any`.
 */

/** Number of points sampled into the lattice. Quoted by the Core screen label. */
export const LATTICE_NODES = 640;

/** Radius of the spherical core, in scene units. */
export const CORE_RADIUS = 1.2;

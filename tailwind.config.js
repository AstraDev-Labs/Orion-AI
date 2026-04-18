/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            fontFamily: {
                mono: ['"Share Tech Mono"', 'monospace'], // Sci-fi font
            },
            colors: {
                cyan: {
                    400: '#22d3ee',
                    500: '#06b6d4',
                    900: '#164e63',
                }
            },
            animation: {
                'tech-spin': 'spin 20s linear infinite',
                'pulse-glow': 'pulse-glow 4s ease-in-out infinite',
                'flicker': 'flicker 0.15s ease-in-out infinite alternate',
                'scanline': 'scanline 8s linear infinite',
            },
            keyframes: {
                'pulse-glow': {
                    '0%, 100%': { opacity: 0.4, filter: 'blur(10px) brightness(1)' },
                    '50%': { opacity: 0.8, filter: 'blur(15px) brightness(1.5)' },
                },
                'flicker': {
                    '0%': { opacity: 0.8 },
                    '100%': { opacity: 1 },
                },
                'scanline': {
                    '0%': { transform: 'translateY(-100%)' },
                    '100%': { transform: 'translateY(100vh)' },
                }
            }
        },
    },
    plugins: [],
}

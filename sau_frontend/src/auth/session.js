let csrfToken = ''

export const getCsrfToken = () => csrfToken
export const setCsrfToken = value => { csrfToken = String(value || '') }
export const clearAuthSession = () => { csrfToken = '' }

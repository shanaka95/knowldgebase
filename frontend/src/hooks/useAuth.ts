import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useState } from "react"

import {
  type Body_login_login_access_token as AccessToken,
  type LoginChallenge,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "@/client"

const isLoggedIn = () => {
  return localStorage.getItem("access_token") !== null
}

const useAuth = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // A correct password buys a challenge, not a session. It lives in memory for
  // the length of one screen: writing it to localStorage would leave a usable
  // half-credential behind on a shared machine long after the user walked away.
  const [challenge, setChallenge] = useState<LoginChallenge | null>(null)

  const { data: user } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    queryFn: async () => (await UsersService.readUserMe()).data,
    enabled: isLoggedIn(),
  })

  const signUpMutation = useMutation({
    mutationFn: async (data: UserRegister) =>
      (await UsersService.registerUser({ body: data })).data,
  })

  // Step one: the password. Never returns a token.
  const loginMutation = useMutation({
    mutationFn: async (data: AccessToken) =>
      (await LoginService.loginAccessToken({ body: data })).data,
    onSuccess: (data) => setChallenge(data),
  })

  // Step two: the emailed code, exchanged for the session.
  const verifyCodeMutation = useMutation({
    mutationFn: async (code: string) => {
      if (!challenge) throw new Error("There is no sign-in in progress.")
      const response = await LoginService.verifyTwoFactor({
        body: { challenge_token: challenge.challenge_token, code },
      })
      return response.data
    },
    onSuccess: (data) => {
      localStorage.setItem("access_token", data.access_token)
      setChallenge(null)
      queryClient.invalidateQueries({ queryKey: ["currentUser"] })
      navigate({ to: "/" })
    },
  })

  const resendCodeMutation = useMutation({
    mutationFn: async () => {
      if (!challenge) throw new Error("There is no sign-in in progress.")
      const response = await LoginService.resendTwoFactor({
        body: { challenge_token: challenge.challenge_token },
      })
      return response.data
    },
    onSuccess: (data) => setChallenge(data),
  })

  const clearChallenge = () => {
    setChallenge(null)
    loginMutation.reset()
    verifyCodeMutation.reset()
    resendCodeMutation.reset()
  }

  const logout = () => {
    localStorage.removeItem("access_token")
    navigate({ to: "/login" })
  }

  return {
    signUpMutation,
    loginMutation,
    verifyCodeMutation,
    resendCodeMutation,
    challenge,
    clearChallenge,
    logout,
    user,
  }
}

export { isLoggedIn }
export default useAuth

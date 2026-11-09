import {
  CognitoIdentityProviderClient,
  ConfirmSignUpCommand,
  InitiateAuthCommand,
  SignUpCommand,
} from "@aws-sdk/client-cognito-identity-provider";

const client = new CognitoIdentityProviderClient({ region: process.env.BHAVS_AWS_REGION ?? "us-east-2" });
const clientId = () => process.env.BHAVS_COGNITO_CLIENT_ID!;

export type Tokens = { idToken: string; accessToken: string; refreshToken?: string; expiresIn: number };

export async function signUp(email: string, password: string) {
  await client.send(
    new SignUpCommand({
      ClientId: clientId(),
      Username: email,
      Password: password,
      UserAttributes: [{ Name: "email", Value: email }],
    }),
  );
}

export async function confirmSignUp(email: string, code: string) {
  await client.send(new ConfirmSignUpCommand({ ClientId: clientId(), Username: email, ConfirmationCode: code }));
}

function toTokens(r: { AuthenticationResult?: { IdToken?: string; AccessToken?: string; RefreshToken?: string; ExpiresIn?: number } }): Tokens {
  const a = r.AuthenticationResult;
  if (!a?.IdToken || !a.AccessToken) throw new Error("No tokens returned");
  return { idToken: a.IdToken, accessToken: a.AccessToken, refreshToken: a.RefreshToken, expiresIn: a.ExpiresIn ?? 3600 };
}

export async function login(email: string, password: string): Promise<Tokens> {
  return toTokens(
    await client.send(
      new InitiateAuthCommand({
        ClientId: clientId(),
        AuthFlow: "USER_PASSWORD_AUTH",
        AuthParameters: { USERNAME: email, PASSWORD: password },
      }),
    ),
  );
}

export async function refresh(refreshToken: string): Promise<Tokens> {
  return toTokens(
    await client.send(
      new InitiateAuthCommand({
        ClientId: clientId(),
        AuthFlow: "REFRESH_TOKEN_AUTH",
        AuthParameters: { REFRESH_TOKEN: refreshToken },
      }),
    ),
  );
}

/** Turn Cognito exceptions into messages that are safe and useful to show. */
export function friendlyError(e: unknown): { message: string; code?: string } {
  const name = (e as { name?: string })?.name;
  const map: Record<string, string> = {
    NotAuthorizedException: "Incorrect email or password.",
    UserNotFoundException: "Incorrect email or password.",
    UserNotConfirmedException: "Please confirm your email first.",
    UsernameExistsException: "An account with this email already exists.",
    InvalidPasswordException: "Password must be 10+ characters with upper, lower case and a number.",
    CodeMismatchException: "That code is not right.",
    ExpiredCodeException: "That code has expired. Sign up again to get a new one.",
    InvalidParameterException: "Please check your details and try again.",
    TooManyRequestsException: "Too many attempts. Wait a minute and try again.",
    LimitExceededException: "Too many attempts. Wait a minute and try again.",
  };
  return { message: (name && map[name]) || "Something went wrong. Please try again.", code: name };
}

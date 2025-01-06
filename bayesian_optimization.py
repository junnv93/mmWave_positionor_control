import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, WhiteKernel
from scipy.stats import norm

class BayesianOptimizer:
    """
    4차원 파라미터 공간(θ, φ, h, p)을 대상으로
    EI(Expected Improvement) 획득 함수를 사용하는 베이지안 최적화 예시.
    """

    def __init__(self, 
                 theta_range=(0, 360),
                 phi_range=(0, 360),
                 h_range=(160, 180),
                 p_range=(0, 180),
                 alpha=1e-3,
                 length_scale=50.0, 
                 n_restarts_optimizer=5):
        """
        파라미터 범위와 GP 파라미터 설정.
        alpha: 관측 노이즈 분산 추정용(너무 작으면 overfitting)
        length_scale: RBF 커널의 길이 스케일 초깃값
        n_restarts_optimizer: GPR 내부 옵티마이저 재시도 횟수
        """
        self.theta_range = theta_range
        self.phi_range = phi_range
        self.h_range = h_range
        self.p_range = p_range

        # GP 커널 설정 (RBF + WhiteKernel)
        kernel = RBF(length_scale=length_scale) + WhiteKernel(noise_level=alpha)
        self.gpr = GaussianProcessRegressor(
            kernel=kernel,
            alpha=0.0,  # WhiteKernel에서 이미 노이즈를 처리
            n_restarts_optimizer=n_restarts_optimizer,
            normalize_y=True
        )

        # 관측 데이터 (X: Nx4, y: Nx1)
        self.X = None
        self.y = None

    def add_observation(self, x, y):
        """
        x: (theta, phi, h, p) 형태의 tuple or list
        y: 스칼라 (채널 파워, EIRP 등)
        """
        x_arr = np.array(x, dtype=float).reshape(1, -1)
        y_arr = np.array([y], dtype=float)
        
        if self.X is None:
            self.X = x_arr
            self.y = y_arr
        else:
            self.X = np.vstack([self.X, x_arr])
            self.y = np.concatenate([self.y, y_arr])

    def train_gp(self):
        """
        현재까지 축적된 (X, y) 데이터를 이용해 GP 학습
        """
        if self.X is None or len(self.X) < 2:
            # 데이터가 너무 적을 경우 그냥 pass
            return
        self.gpr.fit(self.X, self.y)

    def expected_improvement(self, X_candidates, xi=0.01):
        """
        후보 점들(X_candidates)에 대해 EI 값을 계산해 반환.
        X_candidates: shape (M, 4)
        xi: 탐색/활발도 조절 파라미터(Exploration)
        """
        if self.X is None or len(self.X) < 2:
            # 관측값이 거의 없다면, EI 대신 무작위 탐색으로 간주
            return np.random.rand(len(X_candidates))

        # 현재까지의 최대 관측값
        y_max = np.max(self.y)

        # GP 예측(평균, 표준편차)
        mu, std = self.gpr.predict(X_candidates, return_std=True)
        
        # EI 계산
        # z = (mu - y_max - xi) / std
        # EI = (mu - y_max - xi) * Phi(z) + std * phi(z)
        # 단, std=0이면 EI=0
        eps = 1e-9
        std = np.maximum(std, eps)
        z = (mu - y_max - xi) / std
        ei = (mu - y_max - xi) * norm.cdf(z) + std * norm.pdf(z)
        ei = np.maximum(ei, 0.0)
        
        return ei

    def suggest_next_point(self, n_candidates=2000, xi=0.01):
        """
        파라미터 공간에서 무작위로 n_candidates개를 뽑아서
        EI를 계산하고, EI가 최대인 지점을 반환.

        실제 구현에선 BaysOpt 라이브러리나
        혹은 더 정교한 최적화 기법을 사용 가능.
        """
        # 1) 랜덤 샘플 생성
        thetas = np.random.uniform(self.theta_range[0], self.theta_range[1], n_candidates)
        phis = np.random.uniform(self.phi_range[0], self.phi_range[1], n_candidates)
        hs = np.random.uniform(self.h_range[0], self.h_range[1], n_candidates)
        ps = np.random.uniform(self.p_range[0], self.p_range[1], n_candidates)
        
        X_candidates = np.vstack([thetas, phis, hs, ps]).T  # shape (n_candidates, 4)

        # 2) GP 훈련(파라미터 재추정)
        self.train_gp()
        
        # 3) EI 계산
        ei_values = self.expected_improvement(X_candidates, xi=xi)

        # 4) EI 최대 지점 선택
        max_idx = np.argmax(ei_values)
        best_x = X_candidates[max_idx]
        best_ei = ei_values[max_idx]

        return best_x, best_ei

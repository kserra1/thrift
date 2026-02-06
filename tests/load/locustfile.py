from locust import HttpUser, task, between

class ModelUser(HttpUser):
    wait_time = between(0.01, 0.05)  # Very short wait = high concurrency
    
    @task
    def predict(self):
        self.client.post("/predict", json={
            "features": [5.1, 3.5, 1.4, 0.2]
        })

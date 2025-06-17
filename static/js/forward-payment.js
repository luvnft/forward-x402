document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, setting up wallet payment listener');
    
    // Handle payment response
    document.addEventListener('wallet-payment-response', async function(event) {
        console.log('wallet-payment-response received:', event);
        const { success, paymentHeader, error } = event.detail;
        
        if (success) {
            console.log('Payment successful, submitting form with header:', paymentHeader);
            
            // Submit the form with payment header
            const form = document.querySelector('form');
            const formData = new FormData(form);
            const data = {
                email: formData.get('email'),
                subject: formData.get('subject'),
                message: formData.get('message')
            };
            
            try {
                const response = await fetch(window.location.pathname, {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'X-PAYMENT': paymentHeader
                    },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    alert('Email sent successfully!');
                } else {
                    alert('Error: ' + result.error);
                }
            } catch (fetchError) {
                console.error('Fetch error:', fetchError);
                alert('Network error occurred');
            }
        } else {
            alert('Payment failed: ' + error);
        }
    });
}); 
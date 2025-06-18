document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, setting up wallet payment listener');
    
    const payButton = document.querySelector('.wallet-pay');
    
    function setLoading(loading) {
        if (loading) {
            payButton.disabled = true;
            payButton.innerHTML = '<span class="spinner"></span> Sending...';
        } else {
            payButton.disabled = false;
            payButton.innerHTML = 'Pay';
        }
    }
    
    // Handle payment response
    document.addEventListener('wallet-payment-response', async function(event) {
        console.log('wallet-payment-response received:', event);
        const { success, paymentHeader, error } = event.detail;
        
        if (success) {
            // Set the payment header in the input field
            const headerInput = document.querySelector('input[name="x402_header"]');
            if (headerInput) {
                headerInput.value = paymentHeader;
            }
            setLoading(true);
            console.log('Payment successful, submitting form with header:', paymentHeader);
            
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
                setLoading(false);
                
                if (response.ok) {
                    alert('Email sent successfully!');
                } else {
                    alert('Error: ' + result.error);
                }
            } catch (fetchError) {
                console.error('Fetch error:', fetchError);
                setLoading(false);
                alert('Network error occurred');
            }
        } else {
            alert('Payment failed: ' + error);
        }
    });
}); 